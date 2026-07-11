/** Compiled Draft 2020-12 validation for provider-supplied tool arguments. */
import Ajv2020, { type ErrorObject, type ValidateFunction } from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

import { cloneAndFreezeJson, structurallyEqualJson } from "@/events/json";
import type { JSONSchema, ToolSpec } from "@/tools/registry";

export type ToolValidationCode =
  | "INVALID_TOOL_SCHEMA"
  | "INVALID_TOOL_ARGUMENTS"
  | "UNCLASSIFIED_TOOL_RISK";
export type ToolExecutionOutcome = "not_started";
export type ToolArgumentValidator = (toolName: string, args: unknown) => Promise<void>;
export const TOOL_ARGUMENT_VALIDATOR = Symbol("kaji.tool_argument_validator");

const VALIDATION_RECEIPT = Symbol("kaji.validation_receipt");

type ValidationAuthority = ToolArgumentValidator | ValidateFunction;
type ValidationReceiptState = "validated" | "scoped" | "claimed" | "consumed" | "revoked";

interface InternalValidationReceipt {
  readonly toolName: string;
  readonly args: unknown;
  readonly argsSnapshot: unknown;
  readonly authority: ValidationAuthority;
  state: ValidationReceiptState;
}

interface ValidatorState {
  readonly ajv: Ajv2020;
  readonly validators: Map<string, ValidateFunction>;
  readonly argumentValidators: Map<string, ToolArgumentValidator>;
}

// Both registries are weak: neither validated arguments nor validator instances
// are retained after their owning invocation/registry becomes unreachable.
const activeValidationScopes = new WeakMap<object, InternalValidationReceipt>();
const validatorStates = new WeakMap<ToolSchemaValidator, ValidatorState>();

function receiptArgumentsMatch(receipt: InternalValidationReceipt, args: unknown): boolean {
  if (receipt.args !== args) return false;
  try {
    return structurallyEqualJson(receipt.argsSnapshot, args);
  } catch {
    return false;
  }
}

export function attachValidationReceipt<T extends object>(
  context: T,
  receipt: InternalValidationReceipt,
): T {
  if (receipt.state !== "claimed") return context;
  Object.defineProperty(context, VALIDATION_RECEIPT, { value: receipt });
  return context;
}

export function consumeValidationReceipt(
  context: object,
  args: unknown,
  authority: ToolArgumentValidator,
): boolean {
  const receipt = (context as { [VALIDATION_RECEIPT]?: InternalValidationReceipt })[
    VALIDATION_RECEIPT
  ];
  if (receipt === undefined) return false;
  if (
    receipt.state !== "claimed" ||
    !receiptArgumentsMatch(receipt, args) ||
    receipt.authority !== authority
  ) {
    return false;
  }
  receipt.state = "consumed";
  return true;
}

export async function withValidationReceiptScope<T>(
  receipt: InternalValidationReceipt | undefined,
  callback: () => Promise<T>,
): Promise<T> {
  if (receipt === undefined) return callback();
  if (receipt.state !== "validated" || typeof receipt.args !== "object" || receipt.args === null) {
    throw new Error(`Tool validation receipt is not available: ${receipt.toolName}`);
  }
  if (activeValidationScopes.has(receipt.args)) {
    throw new Error(`Tool validation scope is already active: ${receipt.toolName}`);
  }
  receipt.state = "scoped";
  activeValidationScopes.set(receipt.args, receipt);
  try {
    return await callback();
  } finally {
    if (activeValidationScopes.get(receipt.args) === receipt) {
      activeValidationScopes.delete(receipt.args);
    }
    receipt.state = "revoked";
  }
}

export function revokeValidationReceipt(receipt: InternalValidationReceipt | undefined): void {
  if (receipt === undefined) return;
  if (
    typeof receipt.args === "object" &&
    receipt.args !== null &&
    activeValidationScopes.get(receipt.args) === receipt
  ) {
    activeValidationScopes.delete(receipt.args);
  }
  receipt.state = "revoked";
}

function jsonPointer(path: string): string {
  return path.length === 0 ? "/" : path;
}

function jsonPointerParts(path: readonly PropertyKey[]): string {
  if (path.length === 0) return "/";
  return `/${path
    .map((part) => String(part).replaceAll("~", "~0").replaceAll("/", "~1"))
    .join("/")}`;
}

function unsafeJsonPath(
  value: unknown,
  path: readonly PropertyKey[] = [],
  ancestors: Set<object> = new Set(),
): string | undefined {
  if (value === null || typeof value === "string" || typeof value === "boolean") return undefined;
  if (typeof value === "number") return Number.isFinite(value) ? undefined : jsonPointerParts(path);
  if (typeof value !== "object") return jsonPointerParts(path);
  if (ancestors.has(value)) return jsonPointerParts(path);
  if (Array.isArray(value)) {
    if (Object.getOwnPropertySymbols(value).length > 0) return jsonPointerParts(path);
    ancestors.add(value);
    const descriptors = Object.getOwnPropertyDescriptors(value);
    for (let index = 0; index < value.length; index += 1) {
      const descriptor = descriptors[String(index)];
      if (descriptor === undefined || !("value" in descriptor) || !descriptor.enumerable) {
        return jsonPointerParts([...path, index]);
      }
      const invalid = unsafeJsonPath(descriptor.value, [...path, index], ancestors);
      if (invalid !== undefined) return invalid;
    }
    for (const [key, descriptor] of Object.entries(descriptors)) {
      if (key === "length" || !descriptor.enumerable) continue;
      const index = Number(key);
      if (Number.isInteger(index) && index >= 0 && index < value.length && String(index) === key) {
        continue;
      }
      return jsonPointerParts([...path, key]);
    }
    ancestors.delete(value);
    return undefined;
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return jsonPointerParts(path);
  if (Object.getOwnPropertySymbols(value).length > 0) return jsonPointerParts(path);
  ancestors.add(value);
  const descriptors = Object.getOwnPropertyDescriptors(value);
  for (const [key, descriptor] of Object.entries(descriptors)) {
    if (!descriptor.enumerable) continue;
    if (!("value" in descriptor)) return jsonPointerParts([...path, key]);
    const invalid = unsafeJsonPath(descriptor.value, [...path, key], ancestors);
    if (invalid !== undefined) return invalid;
  }
  ancestors.delete(value);
  return undefined;
}

export function assertToolArgumentsJsonSafe(toolName: string, args: unknown): void {
  const path = unsafeJsonPath(args);
  if (path !== undefined) throw ToolArgumentValidationError.jsonUnsafe(toolName, path);
}

/** Return a fresh mutable JSON clone for exactly one tool execution. */
export function cloneToolExecutionArguments<T>(toolName: string, args: T): T {
  assertToolArgumentsJsonSafe(toolName, args);
  try {
    return structuredClone(args);
  } catch {
    throw ToolArgumentValidationError.jsonUnsafe(toolName, "/");
  }
}

function snapshotToolArguments(toolName: string, args: unknown): unknown {
  assertToolArgumentsJsonSafe(toolName, args);
  try {
    return cloneAndFreezeJson(args);
  } catch {
    throw ToolArgumentValidationError.jsonUnsafe(toolName, "/");
  }
}

export function snapshotToolSchemaJson(toolName: string, schema: JSONSchema): JSONSchema {
  const path = unsafeJsonPath(schema);
  if (path !== undefined) throw ToolSchemaValidationError.jsonUnsafe(toolName, path);
  try {
    return cloneAndFreezeJson(schema) as JSONSchema;
  } catch {
    throw ToolSchemaValidationError.jsonUnsafe(toolName, "/");
  }
}

function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function firstError(errors: readonly ErrorObject[]): ErrorObject {
  return [...errors].sort((left, right) => {
    const pathOrder = compareText(jsonPointer(left.instancePath), jsonPointer(right.instancePath));
    return pathOrder || compareText(left.schemaPath, right.schemaPath);
  })[0]!;
}

function boundedMessage(subject: string, keyword: string, path: string): string {
  const message = `${subject} failed ${keyword} validation at ${path}`;
  return message.length <= 200 ? message : `${message.slice(0, 199)}…`;
}

export abstract class ToolValidationError extends Error {
  readonly retryable = false;
  readonly outcome: ToolExecutionOutcome = "not_started";

  protected constructor(
    readonly code: ToolValidationCode,
    readonly toolName: string,
    readonly path: string,
    message: string,
  ) {
    super(message);
    this.name = new.target.name;
  }

  normalized(): { code: ToolValidationCode; path: string; message: string } {
    return { code: this.code, path: this.path, message: this.message };
  }
}

export class ToolArgumentValidationError extends ToolValidationError {
  private constructor(toolName: string, path: string, message: string) {
    super("INVALID_TOOL_ARGUMENTS", toolName, path, message);
  }

  static fromAjv(toolName: string, errors: readonly ErrorObject[]): ToolArgumentValidationError {
    const error = firstError(errors);
    const path = jsonPointer(error.instancePath);
    return new ToolArgumentValidationError(
      toolName,
      path,
      boundedMessage("Tool arguments", error.keyword, path),
    );
  }

  static nonObject(toolName: string): ToolArgumentValidationError {
    return new ToolArgumentValidationError(
      toolName,
      "/",
      "Invalid tool arguments: arguments must be an object",
    );
  }

  static parseError(toolName: string): ToolArgumentValidationError {
    return new ToolArgumentValidationError(
      toolName,
      "/",
      "Invalid tool arguments: arguments were not valid JSON",
    );
  }

  static fromValidationIssue(
    toolName: string,
    pathParts: readonly PropertyKey[],
    keyword: string,
  ): ToolArgumentValidationError {
    const path = jsonPointerParts(pathParts);
    return new ToolArgumentValidationError(
      toolName,
      path,
      boundedMessage("Tool arguments", keyword, path),
    );
  }

  static jsonUnsafe(toolName: string, path: string): ToolArgumentValidationError {
    return new ToolArgumentValidationError(
      toolName,
      path,
      boundedMessage("Tool arguments", "JSON safety", path),
    );
  }

  static oversize(toolName: string): ToolArgumentValidationError {
    return new ToolArgumentValidationError(
      toolName,
      "/",
      "Invalid tool arguments: serialized arguments exceed 65536 bytes",
    );
  }

  static changedDuringValidation(toolName: string): ToolArgumentValidationError {
    return new ToolArgumentValidationError(
      toolName,
      "/",
      "Tool arguments changed during validation at /",
    );
  }
}

export class ToolSchemaValidationError extends ToolValidationError {
  private constructor(toolName: string, path: string, message: string) {
    super("INVALID_TOOL_SCHEMA", toolName, path, message);
  }

  static fromAjv(toolName: string, errors: readonly ErrorObject[]): ToolSchemaValidationError {
    const error = firstError(errors);
    const path = jsonPointer(error.instancePath);
    return new ToolSchemaValidationError(
      toolName,
      path,
      boundedMessage("Tool schema", "schema", path),
    );
  }

  static compilation(toolName: string): ToolSchemaValidationError {
    return new ToolSchemaValidationError(
      toolName,
      "/",
      "Tool schema failed schema validation at /",
    );
  }

  static jsonUnsafe(toolName: string, path: string): ToolSchemaValidationError {
    return new ToolSchemaValidationError(
      toolName,
      path,
      boundedMessage("Tool schema", "JSON safety", path),
    );
  }

  static invalidRisk(toolName: string): ToolSchemaValidationError {
    return new ToolSchemaValidationError(
      toolName,
      "/risk",
      "Tool schema failed risk validation at /risk",
    );
  }
}

export interface ValidationFailureFields {
  error_code: ToolValidationCode;
  error_path: string;
  retryable: false;
  outcome: ToolExecutionOutcome;
}

export function validationFailureFields(error: ToolValidationError): ValidationFailureFields {
  return {
    error_code: error.code,
    error_path: error.path,
    retryable: error.retryable,
    outcome: error.outcome,
  };
}

function validatorState(validator: ToolSchemaValidator): ValidatorState {
  const state = validatorStates.get(validator);
  if (state === undefined) throw new Error("Tool schema validator is not initialized");
  return state;
}

function validationAuthority(
  validator: ToolSchemaValidator,
  name: string,
): ValidationAuthority | undefined {
  const state = validatorState(validator);
  return state.argumentValidators.get(name) ?? state.validators.get(name);
}

async function validateStableArguments(
  name: string,
  args: unknown,
  validate: () => void | Promise<void>,
): Promise<unknown> {
  const snapshot = snapshotToolArguments(name, args);
  await validate();
  assertToolArgumentsJsonSafe(name, args);
  try {
    if (!structurallyEqualJson(snapshot, args)) {
      throw ToolArgumentValidationError.changedDuringValidation(name);
    }
  } catch (error) {
    if (error instanceof ToolArgumentValidationError) throw error;
    throw ToolArgumentValidationError.jsonUnsafe(name, "/");
  }
  return snapshot;
}

async function validateOwnedArguments(
  validator: ToolSchemaValidator,
  name: string,
  args: unknown,
): Promise<{ authority: ValidationAuthority; snapshot: unknown } | undefined> {
  const state = validatorState(validator);
  const argumentValidator = state.argumentValidators.get(name);
  const compiledValidator = state.validators.get(name);
  const authority = argumentValidator ?? compiledValidator;
  if (authority === undefined) return undefined;
  const snapshot = await validateStableArguments(name, args, async () => {
    if (argumentValidator !== undefined) {
      await argumentValidator(name, args);
    } else if (compiledValidator !== undefined && !compiledValidator(args)) {
      throw ToolArgumentValidationError.fromAjv(name, compiledValidator.errors ?? []);
    }
  });
  return { authority, snapshot };
}

/** Compile each tool schema once and validate calls without exposing receipts. */
export class ToolSchemaValidator {
  constructor(specs: ReadonlyMap<string, ToolSpec> = new Map()) {
    const ajv = new Ajv2020({ strict: true, allErrors: true, addUsedSchema: false });
    addFormats(ajv);
    validatorStates.set(this, {
      ajv,
      validators: new Map(),
      argumentValidators: new Map(),
    });
    for (const [name, spec] of specs) addToolSchema(this, name, spec);
  }

  /** Validate a private clone; Zod parse results are intentionally discarded. */
  async validate(name: string, args: unknown): Promise<void> {
    const executionArgs = cloneToolExecutionArguments(name, args);
    await validateOwnedArguments(this, name, executionArgs);
  }
}

/** Internal registration hook used by ToolRegistry without widening the public class API. */
export function addToolSchema(validator: ToolSchemaValidator, name: string, spec: ToolSpec): void {
  const state = validatorState(validator);
  if (state.validators.has(name)) throw new Error(`Tool schema already compiled: ${name}`);
  const schema = snapshotToolSchemaJson(name, spec.parameters);
  let validSchema: boolean | Promise<unknown>;
  try {
    validSchema = state.ajv.validateSchema(schema);
  } catch {
    throw ToolSchemaValidationError.compilation(name);
  }
  if (validSchema instanceof Promise) throw ToolSchemaValidationError.compilation(name);
  if (!validSchema) {
    throw ToolSchemaValidationError.fromAjv(name, state.ajv.errors ?? []);
  }
  let compiledValidator: ValidateFunction;
  try {
    compiledValidator = state.ajv.compile(schema);
  } catch {
    throw ToolSchemaValidationError.compilation(name);
  }
  if ((compiledValidator as ValidateFunction & { $async?: boolean }).$async === true) {
    throw ToolSchemaValidationError.compilation(name);
  }
  state.validators.set(name, compiledValidator);
  const argumentValidator = spec[TOOL_ARGUMENT_VALIDATOR];
  if (argumentValidator !== undefined) state.argumentValidators.set(name, argumentValidator);
}

export function clearToolSchemas(validator: ToolSchemaValidator): void {
  const state = validatorState(validator);
  state.validators.clear();
  state.argumentValidators.clear();
}

export async function validateIsolatedToolArguments(
  name: string,
  args: unknown,
  argumentValidator: ToolArgumentValidator,
): Promise<void> {
  await validateStableArguments(name, args, () => argumentValidator(name, args));
}

export async function validateToolArgumentsForExecution(
  validator: ToolSchemaValidator,
  name: string,
  args: unknown,
): Promise<InternalValidationReceipt | undefined> {
  const proof = await validateOwnedArguments(validator, name, args);
  if (proof === undefined) return undefined;
  return {
    toolName: name,
    args,
    argsSnapshot: proof.snapshot,
    authority: proof.authority,
    state: "validated",
  };
}

export function claimValidationReceipt(
  validator: ToolSchemaValidator,
  receipt: InternalValidationReceipt,
  name: string,
  args: unknown,
): boolean {
  const authority = validationAuthority(validator, name);
  if (
    authority === undefined ||
    (receipt.state !== "validated" && receipt.state !== "scoped") ||
    receipt.toolName !== name ||
    !receiptArgumentsMatch(receipt, args) ||
    receipt.authority !== authority
  ) {
    return false;
  }
  receipt.state = "claimed";
  return true;
}

export function consumeScopedValidationReceipt(
  validator: ToolSchemaValidator,
  name: string,
  args: unknown,
): InternalValidationReceipt | undefined {
  if (typeof args !== "object" || args === null) return undefined;
  const receipt = activeValidationScopes.get(args);
  if (receipt === undefined || !claimValidationReceipt(validator, receipt, name, args)) {
    return undefined;
  }
  activeValidationScopes.delete(args);
  return receipt;
}
