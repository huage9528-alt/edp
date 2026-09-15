import { authHandlers } from "./handlers/auth";
import { eventHandlers } from "./handlers/events";
import { evidenceHandlers } from "./handlers/evidence";
import { registryHandlers } from "./handlers/registry";

export const handlers = [...authHandlers, ...registryHandlers, ...eventHandlers, ...evidenceHandlers];
