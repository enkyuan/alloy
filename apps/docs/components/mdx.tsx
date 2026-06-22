import defaultMdxComponents from "fumadocs-ui/mdx";
import type { MDXComponents } from "mdx/types";
import { Step, Steps } from "fumadocs-ui/components/steps";
import { Tab, Tabs } from "fumadocs-ui/components/tabs";
import { Callout } from "@components/ui/callout";
import { Card, Cards } from "@components/ui/card";
import {
  APIMethod,
  DatabaseTable,
  DividerText,
  Endpoint,
  Features,
  ForkButton,
  GenerateAppleJwt,
  GenerateSecret,
} from "@components/docs/mdx-components";

export function getMDXComponents(components?: MDXComponents) {
  return {
    ...defaultMdxComponents,
    Callout,
    Card,
    Cards,
    Step,
    Steps,
    Tab,
    Tabs,
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

declare global {
  type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
