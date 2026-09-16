import { adapterHandlers } from "./handlers/adapters";
import { auditHandlers } from "./handlers/audit";
import { authHandlers } from "./handlers/auth";
import { ebmsHandlers } from "./handlers/ebms";
import { eventHandlers } from "./handlers/events";
import { evidenceHandlers } from "./handlers/evidence";
import { healthHandlers } from "./handlers/health";
import { qualityHandlers } from "./handlers/quality";
import { registryHandlers } from "./handlers/registry";
import { tenantHandlers } from "./handlers/tenant";

/** W2+W3 六页 MSW 数据层聚合（spec §3 端点清单：27 个 handler）。 */
export const handlers = [
  ...authHandlers,
  ...tenantHandlers,
  ...registryHandlers,
  ...eventHandlers,
  ...evidenceHandlers,
  ...qualityHandlers,
  ...healthHandlers,
  ...adapterHandlers,
  ...ebmsHandlers,
  ...auditHandlers,
];
