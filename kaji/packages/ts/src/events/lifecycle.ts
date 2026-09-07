import {
  SessionPurgeBusyError,
  SessionPurgeUnsupportedError,
  type SessionPurgeComponent,
} from "@/events/errors";
import type { EventStore } from "@/events/store";

/** Internal physical-delete capability; intentionally absent from public barrels. */
export const coordinatedSessionPurge = Symbol("kaji.coordinatedSessionPurge");
/** Internal listener-detach capability; intentionally absent from public barrels. */
export const authorizedListenerTeardown = Symbol("kaji.authorizedListenerTeardown");

export class SessionPurgeAuthorization {}

export interface StoreRuntimeOwner {
  sessionPurgeUnsupportedComponent(): SessionPurgeComponent | undefined;
  isSessionBusy(sessionId: string): boolean;
  closeSessionSubscriptions(
    sessionId: string,
    authorization: SessionPurgeAuthorization,
  ): Promise<void>;
  clearSessionCaches(sessionId: string): void;
  releaseSettledSession(sessionId: string): Promise<void>;
}

export interface StorePurgeBlocker {
  readonly sessionPurgeComponent: SessionPurgeComponent;
}

export interface CoordinatedPurgeableEventStore extends EventStore {
  [coordinatedSessionPurge](
    sessionId: string,
    authorization: SessionPurgeAuthorization,
  ): Promise<boolean>;
}

export interface AuthorizedListenerTeardownStore extends EventStore {
  [authorizedListenerTeardown](
    sessionId: string,
    listeners: readonly object[],
    authorization: SessionPurgeAuthorization,
  ): Promise<void>;
}

interface SessionState {
  activeOperations: number;
  quarantinedProviders: number;
  purging: boolean;
  activeAuthorization?: SessionPurgeAuthorization;
  activeLease?: StoreSessionPurgeLease;
  cleanupPending: boolean;
  cleanupTargets: readonly StoreRuntimeOwner[];
  physicalExisted: boolean;
}

interface StoreState {
  readonly owners: Set<WeakRef<StoreRuntimeOwner>>;
  readonly blockers: Set<StorePurgeBlocker>;
  readonly sessions: Map<string, SessionState>;
}

const STORES = new WeakMap<EventStore, StoreState>();

// Session-generation ordering:
// operation/quarantine -> purge lease -> authorized delete -> cleanup tombstone -> reuse

function storeState(store: EventStore): StoreState {
  let state = STORES.get(store);
  if (state === undefined) {
    state = { owners: new Set(), blockers: new Set(), sessions: new Map() };
    STORES.set(store, state);
  }
  return state;
}

function sessionState(store: EventStore, sessionId: string): [StoreState, SessionState] {
  const stores = storeState(store);
  let session = stores.sessions.get(sessionId);
  if (session === undefined) {
    session = {
      activeOperations: 0,
      quarantinedProviders: 0,
      purging: false,
      cleanupPending: false,
      cleanupTargets: [],
      physicalExisted: false,
    };
    stores.sessions.set(sessionId, session);
  }
  return [stores, session];
}

function releaseSessionState(stores: StoreState, sessionId: string, session: SessionState): void {
  if (
    session.activeOperations === 0 &&
    session.quarantinedProviders === 0 &&
    !session.purging &&
    !session.cleanupPending &&
    stores.sessions.get(sessionId) === session
  ) {
    stores.sessions.delete(sessionId);
  }
}

function liveReferences<T extends object>(references: Set<WeakRef<T>>): T[] {
  const live: T[] = [];
  for (const reference of references) {
    const value = reference.deref();
    if (value === undefined) references.delete(reference);
    else live.push(value);
  }
  return live;
}

export function runtimeOwnersForStore(store: EventStore): readonly StoreRuntimeOwner[] {
  const state = STORES.get(store);
  return state === undefined ? [] : liveReferences(state.owners);
}

function blockersForStore(store: EventStore): readonly StorePurgeBlocker[] {
  const state = STORES.get(store);
  return state === undefined ? [] : [...state.blockers];
}

function blockedRegistrationSession(state: StoreState): string | undefined {
  for (const [sessionId, session] of state.sessions) {
    if (session.purging || session.cleanupPending) return sessionId;
  }
  return undefined;
}

function registerWeak<T extends object>(references: Set<WeakRef<T>>, value: T): () => void {
  liveReferences(references);
  const reference = new WeakRef(value);
  references.add(reference);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    references.delete(reference);
  };
}

export function registerRuntimeOwner(store: EventStore, owner: StoreRuntimeOwner): () => void {
  const state = storeState(store);
  const blocked = blockedRegistrationSession(state);
  if (blocked !== undefined) throw new SessionPurgeBusyError(blocked);
  return registerWeak(state.owners, owner);
}

export function registerPurgeBlocker(store: EventStore, blocker: StorePurgeBlocker): () => void {
  const state = storeState(store);
  const blocked = blockedRegistrationSession(state);
  if (blocked !== undefined) throw new SessionPurgeBusyError(blocked);
  const token: StorePurgeBlocker = Object.freeze({
    sessionPurgeComponent: blocker.sessionPurgeComponent,
  });
  state.blockers.add(token);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    state.blockers.delete(token);
  };
}

export function beginStoreSessionOperation(store: EventStore, sessionId: string): () => void {
  const [stores, session] = sessionState(store, sessionId);
  if (session.purging || session.cleanupPending) {
    releaseSessionState(stores, sessionId, session);
    throw new SessionPurgeBusyError(sessionId);
  }
  session.activeOperations += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    session.activeOperations -= 1;
    releaseSessionState(stores, sessionId, session);
  };
}

export function retainStoreSessionQuarantine(store: EventStore, sessionId: string): () => void {
  const [stores, session] = sessionState(store, sessionId);
  if (session.purging || session.cleanupPending) throw new SessionPurgeBusyError(sessionId);
  session.quarantinedProviders += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    session.quarantinedProviders -= 1;
    releaseSessionState(stores, sessionId, session);
  };
}

export class StoreSessionPurgeLease {
  private released = false;
  authorizationConsumed = false;
  physicalCommitted = false;
  physicalExisted = false;

  constructor(
    readonly store: EventStore,
    readonly sessionId: string,
    readonly authorization: SessionPurgeAuthorization,
    readonly cleanupTargets: readonly StoreRuntimeOwner[],
    readonly recovering: boolean,
    private readonly stores: StoreState,
    readonly session: SessionState,
  ) {}

  result(): boolean {
    return this.recovering ? this.session.physicalExisted : this.physicalExisted;
  }

  release(): void {
    if (this.released) return;
    this.released = true;
    if (this.session.activeLease === this) {
      delete this.session.activeLease;
      delete this.session.activeAuthorization;
      this.session.purging = false;
    }
    releaseSessionState(this.stores, this.sessionId, this.session);
  }
}

export function beginStoreSessionPurge(
  store: EventStore,
  sessionId: string,
  options: { coordinated?: boolean; retryCleanup?: boolean } = {},
): StoreSessionPurgeLease {
  const [stores, session] = sessionState(store, sessionId);
  if (session.purging || session.activeOperations > 0 || session.quarantinedProviders > 0) {
    releaseSessionState(stores, sessionId, session);
    throw new SessionPurgeBusyError(sessionId);
  }
  const blockers = blockersForStore(store);
  if (blockers.length > 0) {
    releaseSessionState(stores, sessionId, session);
    throw new SessionPurgeUnsupportedError(sessionId, blockers[0]!.sessionPurgeComponent);
  }
  const owners = runtimeOwnersForStore(store);
  let targets: readonly StoreRuntimeOwner[];
  let recovering: boolean;
  if (session.cleanupPending) {
    if (options.coordinated !== true || options.retryCleanup !== true) {
      throw new SessionPurgeBusyError(sessionId);
    }
    targets = session.cleanupTargets;
    recovering = true;
  } else {
    if (owners.length > 0 && options.coordinated !== true) {
      releaseSessionState(stores, sessionId, session);
      throw new SessionPurgeBusyError(sessionId);
    }
    targets = owners;
    recovering = false;
  }
  const authorization = new SessionPurgeAuthorization();
  const lease = new StoreSessionPurgeLease(
    store,
    sessionId,
    authorization,
    targets,
    recovering,
    stores,
    session,
  );
  session.purging = true;
  session.activeAuthorization = authorization;
  session.activeLease = lease;
  return lease;
}

function assertActiveLease(lease: StoreSessionPurgeLease): void {
  const { session } = lease;
  if (
    !session.purging ||
    session.activeLease !== lease ||
    session.activeAuthorization !== lease.authorization
  ) {
    throw new SessionPurgeBusyError(lease.sessionId);
  }
}

export function authorizedSessionTeardown<T>(
  store: EventStore,
  sessionId: string,
  authorization: SessionPurgeAuthorization,
  operation: () => T,
): T {
  const session = STORES.get(store)?.sessions.get(sessionId);
  const lease = session?.activeLease;
  if (
    session === undefined ||
    lease === undefined ||
    !session.purging ||
    session.activeAuthorization !== authorization ||
    lease.authorizationConsumed
  ) {
    throw new SessionPurgeBusyError(sessionId);
  }
  return operation();
}

export function assertPhysicalPurgeAuthorized(
  store: EventStore,
  sessionId: string,
  authorization: SessionPurgeAuthorization,
): StoreSessionPurgeLease {
  const session = STORES.get(store)?.sessions.get(sessionId);
  const lease = session?.activeLease;
  if (
    lease === undefined ||
    lease.store !== store ||
    lease.sessionId !== sessionId ||
    lease.authorization !== authorization ||
    session?.activeAuthorization !== authorization ||
    lease.recovering ||
    lease.authorizationConsumed
  ) {
    throw new SessionPurgeBusyError(sessionId);
  }
  lease.authorizationConsumed = true;
  return lease;
}

export function markPhysicalPurgeCommitted(lease: StoreSessionPurgeLease): void {
  assertActiveLease(lease);
  if (!lease.authorizationConsumed || lease.physicalCommitted) {
    throw new SessionPurgeBusyError(lease.sessionId);
  }
  lease.physicalCommitted = true;
  lease.session.cleanupTargets = lease.cleanupTargets;
  lease.session.cleanupPending = true;
  lease.session.physicalExisted = lease.physicalExisted;
}

export function finishSessionCleanup(lease: StoreSessionPurgeLease): void {
  assertActiveLease(lease);
  if (!lease.session.cleanupPending) throw new SessionPurgeBusyError(lease.sessionId);
  lease.session.cleanupTargets = [];
  lease.session.cleanupPending = false;
  lease.session.physicalExisted = false;
}

export function supportsCoordinatedSessionPurge(
  store: EventStore,
): store is CoordinatedPurgeableEventStore {
  return (
    typeof (store as Partial<CoordinatedPurgeableEventStore>)[coordinatedSessionPurge] ===
    "function"
  );
}

export function supportsAuthorizedListenerTeardown(
  store: EventStore,
): store is AuthorizedListenerTeardownStore {
  return (
    typeof (store as Partial<AuthorizedListenerTeardownStore>)[authorizedListenerTeardown] ===
    "function"
  );
}
