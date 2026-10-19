import base from "./vite.config";
export default { ...base, server: { ...(base as { server?: object }).server, hmr: false, watch: null } };
