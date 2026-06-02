import { createFileRoute, redirect } from "@tanstack/react-router";
import { SignupPage } from "@components/pages/signup";

export const Route = createFileRoute("/signup/")({
  beforeLoad: ({ context }) => {
    if (context.session) {
      throw redirect({ to: "/dashboard" });
    }
  },
  component: SignupPage,
});
