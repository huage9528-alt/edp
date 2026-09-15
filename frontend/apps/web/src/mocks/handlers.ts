import { authHandlers } from "./handlers/auth";
import { registryHandlers } from "./handlers/registry";

export const handlers = [...authHandlers, ...registryHandlers];
