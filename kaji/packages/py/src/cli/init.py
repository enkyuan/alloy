"""`kaji init` -- scaffold a new project."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import stat as stat_module
import sys
import uuid

from .templates import agent_template, env_template

PROVIDERS = ["mock", "openai", "anthropic"]
_REQUIRED_DIR_FD = frozenset({os.open, os.stat, os.link, os.rename, os.unlink})
_REQUIRED_NOFOLLOW = frozenset({os.stat, os.link})
_BACKUP_BASENAME = re.compile(r"^\.[A-Za-z0-9._-]+\.kaji-backup-[0-9a-f]{32}\.tmp$")


class ScaffoldRollbackError(OSError):
    """Rollback failed and one or more generated backup files were retained."""

    def __init__(self, backup_names: set[str] | tuple[str, ...]) -> None:
        self.backup_names = tuple(
            sorted(name for name in backup_names if _BACKUP_BASENAME.fullmatch(name))
        )
        super().__init__("scaffold publication rollback failed")


def _safe_directory_flags() -> tuple[int, int]:
    try:
        directory_flag = os.O_DIRECTORY
        nofollow_flag = os.O_NOFOLLOW
        supports_dir_fd = os.supports_dir_fd
        supports_follow_symlinks = os.supports_follow_symlinks
    except AttributeError:
        raise OSError("safe scaffold directory operations are unsupported") from None
    if not _REQUIRED_DIR_FD <= supports_dir_fd or not _REQUIRED_NOFOLLOW <= (
        supports_follow_symlinks
    ):
        raise OSError("safe scaffold directory operations are unsupported")
    return directory_flag, nofollow_flag


def _open_directory(target: Path) -> int:
    directory_flag, nofollow_flag = _safe_directory_flags()
    return os.open(target, os.O_RDONLY | directory_flag | nofollow_flag)


def _directory_identity(directory_fd: int) -> tuple[int, int]:
    directory_stat = os.fstat(directory_fd)
    return directory_stat.st_dev, directory_stat.st_ino


def _target_has_identity(target: Path, identity: tuple[int, int]) -> bool:
    try:
        reopened = _open_directory(target)
    except OSError:
        return False
    try:
        return _directory_identity(reopened) == identity
    finally:
        os.close(reopened)


def _stat_name(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _create_temp(directory_fd: int, prefix: str) -> tuple[int, str]:
    _directory_flag, nofollow_flag = _safe_directory_flags()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow_flag
    for _attempt in range(100):
        name = f"{prefix}{uuid.uuid4().hex}.tmp"
        try:
            return os.open(name, flags, 0o600, dir_fd=directory_fd), name
        except FileExistsError:
            continue
    raise FileExistsError("could not allocate a unique scaffold temporary file")


def _unlink_if_present(directory_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=directory_fd)
    except FileNotFoundError:
        pass


def _publish_force(
    directory_fd: int,
    sources: list[str],
    destinations: list[str],
    *,
    target: Path,
    target_identity: tuple[int, int],
) -> None:
    replaced: list[tuple[str, tuple[int, int], str | None]] = []
    backups: list[str] = []
    preserve_backups: set[str] = set()
    try:
        for source, destination in zip(sources, destinations, strict=True):
            source_stat = os.stat(source, dir_fd=directory_fd, follow_symlinks=False)
            backup: str | None = None
            destination_stat = _stat_name(directory_fd, destination)
            if destination_stat is not None:
                if stat_module.S_ISLNK(destination_stat.st_mode):
                    raise ValueError(
                        "unsafe scaffold destination: symbolic links are not allowed"
                    )
                if not stat_module.S_ISREG(destination_stat.st_mode):
                    raise OSError("scaffold destination is not a regular file")
                descriptor, backup = _create_temp(
                    directory_fd,
                    prefix=f".{destination}.kaji-backup-",
                )
                os.close(descriptor)
                backups.append(backup)
                os.rename(
                    destination,
                    backup,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
                replaced.append(
                    (destination, (source_stat.st_dev, source_stat.st_ino), backup)
                )
                backup_stat = os.stat(
                    backup, dir_fd=directory_fd, follow_symlinks=False
                )
                if stat_module.S_ISLNK(backup_stat.st_mode) or (
                    backup_stat.st_dev,
                    backup_stat.st_ino,
                ) != (destination_stat.st_dev, destination_stat.st_ino):
                    raise ValueError(
                        "unsafe scaffold destination: destination changed during write"
                    )
            else:
                replaced.append(
                    (destination, (source_stat.st_dev, source_stat.st_ino), None)
                )
            os.rename(
                source,
                destination,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
        if not _target_has_identity(target, target_identity):
            raise ValueError(
                "unsafe scaffold destination: target directory changed during write"
            )
    except BaseException:
        rollback_error: OSError | None = None
        for destination, identity, backup in reversed(replaced):
            try:
                if backup is not None:
                    destination_stat = _stat_name(directory_fd, destination)
                    if destination_stat is not None:
                        if (
                            destination_stat.st_dev,
                            destination_stat.st_ino,
                        ) != identity:
                            preserve_backups.add(backup)
                            raise OSError(
                                "scaffold destination changed during rollback; "
                                f"original preserved at {backup}"
                            )
                    os.rename(
                        backup,
                        destination,
                        src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd,
                    )
                else:
                    destination_stat = _stat_name(directory_fd, destination)
                    if (
                        destination_stat is not None
                        and (
                            destination_stat.st_dev,
                            destination_stat.st_ino,
                        )
                        == identity
                    ):
                        os.unlink(destination, dir_fd=directory_fd)
            except OSError as error:
                rollback_error = rollback_error or error
                if backup is not None:
                    preserve_backups.add(backup)
        if rollback_error is not None:
            raise ScaffoldRollbackError(preserve_backups) from rollback_error
        raise
    finally:
        for name in sources:
            _unlink_if_present(directory_fd, name)
        for name in backups:
            if name in preserve_backups:
                continue
            _unlink_if_present(directory_fd, name)


def init_project(
    target: Path, *, provider: str = "mock", force: bool = False
) -> list[Path]:
    files = (
        ("agent.py", agent_template(provider)),
        (".env.example", env_template(provider)),
    )
    target.mkdir(parents=True, exist_ok=True)
    directory_fd = _open_directory(target)
    target_identity = _directory_identity(directory_fd)
    destinations = [name for name, _body in files]
    temporary: list[str] = []
    committed: list[tuple[str, tuple[int, int]]] = []
    try:
        destination_stats = [_stat_name(directory_fd, name) for name in destinations]
        if any(
            item is not None and stat_module.S_ISLNK(item.st_mode)
            for item in destination_stats
        ):
            raise ValueError(
                "unsafe scaffold destination: symbolic links are not allowed"
            )
        if not force and any(item is not None for item in destination_stats):
            return []

        for name, body in files:
            descriptor, temporary_name = _create_temp(
                directory_fd, prefix=f".{name}.kaji-"
            )
            temporary.append(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())

        destination_stats = [_stat_name(directory_fd, name) for name in destinations]
        if any(
            item is not None and stat_module.S_ISLNK(item.st_mode)
            for item in destination_stats
        ):
            raise ValueError(
                "unsafe scaffold destination: symbolic links are not allowed"
            )
        if not force and any(item is not None for item in destination_stats):
            return []

        if force:
            _publish_force(
                directory_fd,
                temporary,
                destinations,
                target=target,
                target_identity=target_identity,
            )
        else:
            for source, destination in zip(temporary, destinations, strict=True):
                source_stat = os.stat(
                    source, dir_fd=directory_fd, follow_symlinks=False
                )
                os.link(
                    source,
                    destination,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                committed.append(
                    (destination, (source_stat.st_dev, source_stat.st_ino))
                )
            if not _target_has_identity(target, target_identity):
                raise ValueError(
                    "unsafe scaffold destination: target directory changed during write"
                )
        return [target / name for name in destinations]
    except BaseException:
        for destination, identity in committed:
            destination_stat = _stat_name(directory_fd, destination)
            if (
                destination_stat is not None
                and (
                    destination_stat.st_dev,
                    destination_stat.st_ino,
                )
                == identity
            ):
                os.unlink(destination, dir_fd=directory_fd)
        raise
    finally:
        for name in temporary:
            _unlink_if_present(directory_fd, name)
        os.close(directory_fd)


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("init", help="scaffold a new kaji project")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--provider", choices=PROVIDERS, default="mock")
    p.add_argument("--force", action="store_true")
    p.add_argument("--yes", action="store_true", help="non-interactive")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    target = Path(args.path)
    try:
        written = init_project(target, provider=args.provider, force=args.force)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError as error:
        message = "kaji init failed while writing the scaffold"
        if isinstance(error, ScaffoldRollbackError) and error.backup_names:
            message += "; original preserved in target directory as " + ", ".join(
                error.backup_names
            )
        print(message, file=sys.stderr)
        return 1
    if not written:
        conflicts = [
            path.name
            for path in (target / "agent.py", target / ".env.example")
            if path.exists()
        ]
        print(
            "refusing to overwrite without --force: " + ", ".join(conflicts),
            file=sys.stderr,
        )
        return 1
    for p in written:
        print(p)
    return 0
