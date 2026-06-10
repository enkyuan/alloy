import { createRootRoute, Outlet } from "@tanstack/react-router";
import { Agentation } from "agentation";
import { authClient } from "@lib/auth";

export const Route = createRootRoute({
  beforeLoad: async () => {
    const { data: session } = await authClient.getSession();
    return { session };
  },
  component: () => (
    <>
      <Outlet />
      {import.meta.env.DEV && <Agentation />}
    </>
  ),
});
