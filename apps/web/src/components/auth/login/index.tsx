import { useState } from "react";
import { useForm } from "@tanstack/react-form";
import { Link, useNavigate } from "@tanstack/react-router";
import { z } from "zod";
import { authClient } from "@lib/auth";
import { Button } from "@components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@components/ui/field";
import { Input } from "@components/ui/input";

const emailSchema = z.email("Enter a valid email");
const passwordSchema = z.string().min(8, "Password must be at least 8 characters");

function zodValidator<T>(schema: z.ZodType<T>) {
  return ({ value }: { value: T }) => {
    const result = schema.safeParse(value);
    return result.success ? undefined : result.error.issues[0]?.message;
  };
}

export function LoginForm({ className }: { className?: string }) {
  const [serverError, setServerError] = useState<string | null>(null);
  const navigate = useNavigate();

  const form = useForm({
    defaultValues: { email: "", password: "" },
    onSubmit: async ({ value }) => {
      setServerError(null);
      const { error } = await authClient.signIn.email({
        email: value.email,
        password: value.password,
      });
      if (error) {
        setServerError(error.message ?? "Sign in failed");
      } else {
        void navigate({ to: "/dashboard" });
      }
    },
  });

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Login to your account</CardTitle>
        <CardDescription>Enter your email below to login to your account</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            e.stopPropagation();
            void form.handleSubmit();
          }}
        >
          <FieldGroup>
            <form.Field name="email" validators={{ onChange: zodValidator(emailSchema) }}>
              {(field) => (
                <Field>
                  <FieldLabel htmlFor={field.name}>Email</FieldLabel>
                  <Input
                    id={field.name}
                    name={field.name}
                    type="email"
                    placeholder="m@example.com"
                    aria-invalid={field.state.meta.errors.length > 0}
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                  />
                  {field.state.meta.errors.length > 0 && (
                    <FieldDescription className="text-destructive">
                      {String(field.state.meta.errors[0])}
                    </FieldDescription>
                  )}
                </Field>
              )}
            </form.Field>

            <form.Field name="password" validators={{ onChange: zodValidator(passwordSchema) }}>
              {(field) => (
                <Field>
                  <FieldLabel htmlFor={field.name}>Password</FieldLabel>
                  <Input
                    id={field.name}
                    name={field.name}
                    type="password"
                    aria-invalid={field.state.meta.errors.length > 0}
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                  />
                  {field.state.meta.errors.length > 0 && (
                    <FieldDescription className="text-destructive">
                      {String(field.state.meta.errors[0])}
                    </FieldDescription>
                  )}
                </Field>
              )}
            </form.Field>

            {serverError && (
              <FieldDescription className="text-destructive">{serverError}</FieldDescription>
            )}

            <form.Subscribe selector={(s) => [s.canSubmit, s.isSubmitting]}>
              {([canSubmit, isSubmitting]) => (
                <Field>
                  <Button type="submit" className="w-full" disabled={!canSubmit}>
                    {isSubmitting ? "Logging in..." : "Login"}
                  </Button>
                </Field>
              )}
            </form.Subscribe>
          </FieldGroup>
        </form>
        <div className="mt-4 text-center text-xs text-muted-foreground">
          Don't have an account?{" "}
          <Link
            to="/signup"
            className="text-primary underline underline-offset-4 hover:text-primary/80"
          >
            Sign up
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
