import { Link } from "@tanstack/react-router";

export function Home() {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-4">
      <h1 className="text-2xl font-medium">agentpay</h1>
      <Link to="/login" className="text-primary underline underline-offset-4">
        Go to login
      </Link>
    </main>
  );
}
