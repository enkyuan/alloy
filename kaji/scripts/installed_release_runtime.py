#!/usr/bin/env python3
"""Install verified Kaji release archives into one isolated benchmark runtime."""

from __future__ import annotations

import base64
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import MappingProxyType
from typing import Any

from process_runner import PACKAGE_COMMAND_BUDGET, run_checked
from verify_release_artifacts import VerifiedReleaseArtifacts, verify


ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "kaji"
TS = ROOT / "kaji" / "ts"
TS_BENCHMARK = TS / "benchmarks" / "runtime-benchmark.ts"
TS_SOAK = TS / "benchmarks" / "runtime-soak.ts"
TS_CONSUMER = Path(__file__).with_name("installed-typescript-runtime")
TS_CONSUMER_MANIFEST = TS_CONSUMER / "package.core.json"
TS_CONSUMER_LOCK = TS_CONSUMER / "package-lock.core.json"
TS_OPENAI_CONSUMER_MANIFEST = TS_CONSUMER / "package.openai.json"
TS_OPENAI_CONSUMER_LOCK = TS_CONSUMER / "package-lock.openai.json"
SAFE_PARENT_ENV = (
    "PATH",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


@dataclass(frozen=True, slots=True)
class InstalledReleaseRuntime:
    root: Path
    python_executable: Path
    typescript_workdir: Path
    typescript_benchmark: Path
    typescript_soak: Path
    resolved_python_package: Path
    resolved_typescript_package: Path
    typescript_lock_template_sha256: str
    typescript_lock_rendered_sha256: str
    release: VerifiedReleaseArtifacts
    environment: Mapping[str, str]

    def identity(self) -> dict[str, Any]:
        return {
            "commit": self.release.commit,
            "releaseManifestSha256": self.release.manifest_sha256,
            "artifacts": {
                "python": {
                    "file": self.release.python_wheel.name,
                    "sha256": self.release.artifact_sha256[
                        self.release.python_wheel.name
                    ],
                },
                "typescript": {
                    "file": self.release.npm_tarball.name,
                    "sha256": self.release.artifact_sha256[
                        self.release.npm_tarball.name
                    ],
                },
            },
            "resolvedPackages": {
                "python": str(self.resolved_python_package),
                "typescript": str(self.resolved_typescript_package),
            },
            "typescriptConsumerLock": {
                "templateSha256": self.typescript_lock_template_sha256,
                "renderedSha256": self.typescript_lock_rendered_sha256,
            },
        }


def _require_contained(path: Path, root: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        isolated = root.resolve(strict=True)
    except OSError as error:
        raise RuntimeError(f"{label} package path is missing") from error
    if not resolved.is_relative_to(isolated):
        raise RuntimeError(f"{label} package resolved outside the isolated runtime")
    return resolved


def _safe_environment(root: Path) -> dict[str, str]:
    environment = {
        name: value for name in SAFE_PARENT_ENV if (value := os.environ.get(name))
    }
    if "PATH" not in environment:
        raise RuntimeError("PATH is required to construct the installed runtime")
    home = root / "home"
    temporary = root / "tmp"
    cache = root / "cache"
    for directory in (home, temporary, cache):
        directory.mkdir(parents=True)
    environment.update(
        {
            "HOME": str(home),
            "TMPDIR": str(temporary),
            "XDG_CACHE_HOME": str(cache),
            "UV_CACHE_DIR": str(cache / "uv"),
            "npm_config_cache": str(cache / "npm"),
            "npm_config_audit": "false",
            "npm_config_fund": "false",
            "npm_config_ignore_scripts": "true",
            "PYTHONNOUSERSITE": "1",
            "PYTHONSAFEPATH": "1",
        }
    )
    return environment


def _capture_json(command: list[str], *, cwd: Path, env: Mapping[str, str]) -> Any:
    completed = run_checked(
        command,
        cwd=cwd,
        budget=PACKAGE_COMMAND_BUDGET,
        capture=True,
        env=env,
    )
    try:
        return json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("installed package resolver emitted invalid JSON") from error


def _install_python(
    root: Path,
    release: VerifiedReleaseArtifacts,
    environment: Mapping[str, str],
    *,
    include_openai: bool,
) -> tuple[Path, Path]:
    uv = shutil.which("uv", path=environment["PATH"])
    if uv is None:
        raise RuntimeError("uv is required to construct the installed runtime")
    venv = root / "python"
    requirements = root / "python-requirements.txt"
    run_checked(
        [uv, "venv", "--python", sys.executable, str(venv)],
        cwd=root,
        budget=PACKAGE_COMMAND_BUDGET,
        env=environment,
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    provider_extras = ["--extra", "openai"] if include_openai else []
    run_checked(
        [
            uv,
            "export",
            "--project",
            str(SDK),
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            *provider_extras,
            "--format",
            "requirements-txt",
            "--output-file",
            str(requirements),
        ],
        cwd=root,
        budget=PACKAGE_COMMAND_BUDGET,
        env=environment,
    )
    run_checked(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--require-hashes",
            "--no-deps",
            "--requirements",
            str(requirements),
        ],
        cwd=root,
        budget=PACKAGE_COMMAND_BUDGET,
        env=environment,
    )
    run_checked(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            str(release.python_wheel),
        ],
        cwd=root,
        budget=PACKAGE_COMMAND_BUDGET,
        env=environment,
    )
    resolved = _capture_json(
        [
            str(python),
            "-I",
            "-c",
            (
                "import json, pathlib, kaji; "
                "print(json.dumps(str(pathlib.Path(kaji.__file__).resolve())))"
            ),
        ],
        cwd=root,
        env=environment,
    )
    if not isinstance(resolved, str):
        raise RuntimeError("installed Python resolver returned a non-path value")
    return python, _require_contained(Path(resolved), venv, "python")


def _install_typescript(
    root: Path,
    release: VerifiedReleaseArtifacts,
    environment: Mapping[str, str],
    *,
    include_openai: bool,
) -> tuple[Path, Path, Path, Path, str, str]:
    npm = shutil.which("npm", path=environment["PATH"])
    node = shutil.which("node", path=environment["PATH"])
    if npm is None or node is None:
        raise RuntimeError(
            "node and npm are required to construct the installed runtime"
        )
    consumer = root / "typescript"
    consumer.mkdir()
    template_hash, rendered_hash = _render_typescript_consumer(
        consumer,
        release.npm_tarball,
        include_openai=include_openai,
    )
    run_checked(
        [
            npm,
            "ci",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
        ],
        cwd=consumer,
        budget=PACKAGE_COMMAND_BUDGET,
        env=environment,
    )
    if _sha256(consumer / "package-lock.json") != rendered_hash:
        raise RuntimeError("npm ci changed the rendered consumer lock")
    benchmark = consumer / "runtime-benchmark.ts"
    soak = consumer / "runtime-soak.ts"
    shutil.copy2(TS_BENCHMARK, benchmark)
    shutil.copy2(TS_SOAK, soak)
    resolved = _capture_json(
        [
            node,
            "--input-type=module",
            "--eval",
            (
                "import { realpathSync } from 'node:fs'; "
                "import { dirname, join } from 'node:path'; "
                "import { fileURLToPath } from 'node:url'; "
                "await import('kaji-sdk'); "
                "const entry=fileURLToPath(import.meta.resolve('kaji-sdk')); "
                "console.log(JSON.stringify(realpathSync(join(dirname(entry), '..'))));"
            ),
        ],
        cwd=consumer,
        env=environment,
    )
    if not isinstance(resolved, str):
        raise RuntimeError("installed TypeScript resolver returned a non-path value")
    package = _require_contained(Path(resolved), consumer, "typescript")
    return consumer, benchmark, soak, package, template_hash, rendered_hash


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _typescript_consumer_fixture(include_openai: bool) -> tuple[Path, Path]:
    if include_openai:
        return TS_OPENAI_CONSUMER_MANIFEST, TS_OPENAI_CONSUMER_LOCK
    return TS_CONSUMER_MANIFEST, TS_CONSUMER_LOCK


def _render_typescript_consumer(
    consumer: Path,
    tarball: Path,
    *,
    include_openai: bool = False,
) -> tuple[str, str]:
    manifest_path, lock_path = _typescript_consumer_fixture(include_openai)
    try:
        manifest_bytes = manifest_path.read_bytes()
        template_bytes = lock_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        template = json.loads(template_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "installed TypeScript consumer fixture is invalid"
        ) from error
    packages = template.get("packages")
    root_package = packages.get("") if isinstance(packages, dict) else None
    sdk_package = (
        packages.get("node_modules/kaji-sdk") if isinstance(packages, dict) else None
    )
    if (
        not isinstance(manifest, dict)
        or not isinstance(root_package, dict)
        or not isinstance(sdk_package, dict)
        or root_package.get("dependencies") != manifest.get("dependencies")
        or sdk_package.get("resolved") != "file:kaji-sdk-0.2.0-beta.3.tgz"
        or not isinstance(sdk_package.get("integrity"), str)
    ):
        raise RuntimeError("installed TypeScript consumer fixture is inconsistent")

    copied_tarball = consumer / "kaji-sdk-0.2.0-beta.3.tgz"
    shutil.copyfile(tarball, copied_tarball)
    (consumer / "package.json").write_bytes(manifest_bytes)
    rendered = copy.deepcopy(template)
    rendered_sdk = rendered["packages"]["node_modules/kaji-sdk"]
    digest = hashlib.sha512(copied_tarball.read_bytes()).digest()
    rendered_sdk["integrity"] = "sha512-" + base64.b64encode(digest).decode("ascii")

    comparison = copy.deepcopy(rendered)
    comparison["packages"]["node_modules/kaji-sdk"]["integrity"] = sdk_package[
        "integrity"
    ]
    if comparison != template:
        raise RuntimeError("rendered consumer lock changed frozen registry packages")
    rendered_bytes = (json.dumps(rendered, indent=2) + "\n").encode("utf-8")
    rendered_lock = consumer / "package-lock.json"
    rendered_lock.write_bytes(rendered_bytes)
    return hashlib.sha256(template_bytes).hexdigest(), hashlib.sha256(
        rendered_bytes
    ).hexdigest()


@contextmanager
def installed_release_runtime(
    artifacts_dir: Path,
    *,
    expected_commit: str,
    include_openai: bool = False,
) -> Iterator[InstalledReleaseRuntime]:
    release = verify(artifacts_dir, expected_commit)
    with tempfile.TemporaryDirectory(prefix="kaji-installed-release-") as temporary:
        root = Path(temporary).resolve()
        environment = _safe_environment(root)
        python, python_package = _install_python(
            root,
            release,
            environment,
            include_openai=include_openai,
        )
        (
            consumer,
            benchmark,
            soak,
            typescript_package,
            lock_template_hash,
            lock_rendered_hash,
        ) = _install_typescript(
            root,
            release,
            environment,
            include_openai=include_openai,
        )
        runtime = InstalledReleaseRuntime(
            root=root,
            python_executable=python,
            typescript_workdir=consumer,
            typescript_benchmark=benchmark,
            typescript_soak=soak,
            resolved_python_package=python_package,
            resolved_typescript_package=typescript_package,
            typescript_lock_template_sha256=lock_template_hash,
            typescript_lock_rendered_sha256=lock_rendered_hash,
            release=release,
            environment=MappingProxyType(dict(environment)),
        )
        yield runtime
        if verify(artifacts_dir, expected_commit) != release:
            raise RuntimeError("release artifacts changed while evidence was running")
