import { betterAuth } from "better-auth";
import { jwt, organization } from "better-auth/plugins";
import { Pool } from "pg";

const pool = new Pool({ connectionString: process.env.DATABASE_URL });

export const auth = betterAuth({
  database: pool,
  secret: process.env.BETTER_AUTH_SECRET,
  trustedOrigins: (process.env.TRUSTED_ORIGINS ?? "http://localhost:5173").split(","),

  emailAndPassword: {
    enabled: true,
    requireEmailVerification: false,
  },

  plugins: [
    jwt({
      jwt: {
        expirationTime: "7d",
        additionalFields: {
          orgId: {
            description: "Active organization ID",
            type: "string",
            required: false,
          },
        },
      },
    }),
    organization(),
  ],
});

export type Auth = typeof auth;
