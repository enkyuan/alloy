import { Login } from "@/components/auth/login";

export function LoginPage() {
  return (
    <main className="flex min-h-svh items-center justify-center p-6 md:p-10">
      <div className="w-full max-w-sm">
        <Login />
      </div>
    </main>
  );
}
