const SENSITIVE = [
  "secret",
  "clientsecret",
  "clientid",
  "authtoken",
  "apikey",
  "apisecret",
  "privatekey",
  "publickey",
  "password",
  "token",
  "webhook",
  "connectionstring",
  "databaseurl",
];

const ALLOWED = ["baseurl", "callbackurl", "redirecturl", "trustedorigins", "appname"];

function isSensitive(key: string): boolean {
  const k = key.toLowerCase();
  if (ALLOWED.includes(k)) return false;
  return SENSITIVE.some((s) => k === s || k.endsWith(s));
}

export function redact(value: unknown, parentKey?: string): unknown {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.map((v) => redact(v, parentKey));
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (isSensitive(k) && typeof v === "string" && v.length > 0) {
        out[k] = "[REDACTED]";
      } else {
        out[k] = redact(v, k);
      }
    }
    return out;
  }
  if (typeof value === "string" && parentKey && isSensitive(parentKey) && value.length > 0) {
    return "[REDACTED]";
  }
  return value;
}
