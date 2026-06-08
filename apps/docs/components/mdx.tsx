import defaultMdxComponents from "fumadocs-ui/mdx";
import type { MDXComponents } from "mdx/types";
import { Callout } from "@/components/ui/callout";
import { Card, Cards } from "@/components/ui/card";
import {
  APIMethod,
  DatabaseTable,
  DividerText,
  Endpoint,
  Features,
  ForkButton,
  GenerateAppleJwt,
  GenerateSecret,
} from "@/components/docs/mdx-components";

export function getMDXComponents(components?: MDXComponents) {
  return {
    ...defaultMdxComponents,
    Callout,
    Card,
    Cards,
    APIMethod,
    DatabaseTable,
    DividerText,
    Endpoint,
    Features,
    ForkButton,
    GenerateAppleJwt,
    GenerateSecret,
    ...components,
  } satisfies MDXComponents;
}

export const useMDXComponents = getMDXComponents;

declare global {
  type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
