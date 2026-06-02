import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/dashboard/")({
  beforeLoad: ({ context }) => {
    if (!context.session) {
      throw redirect({ to: "/login" });
    }
  },
  component: DashboardPage,
});

function DashboardPage() {
  return (
    <main className="flex min-h-svh items-center justify-center p-6 md:p-10">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
    </main>
  );
}
