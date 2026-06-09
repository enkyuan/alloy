import type React from "react";

export interface NavFileItem {
  name: string;
  href: string;
  path?: string;
  external?: boolean;
}

export interface ProductItem {
  title: string;
  tagline: string;
  description: string;
  href: string;
  activatesTab?: boolean;
  Icon: React.ComponentType<{ className?: string }>;
  Pattern?: React.FC<{ className?: string }>;
  patternClassName?: string;
  BgPattern?: React.FC<{ className?: string }>;
  bgPatternClassName?: string;
}

export interface LinkResource {
  title: string;
  href: string;
  Icon: React.ComponentType<{ className?: string }>;
}

export interface MobileMenuSection {
  name: string;
  href?: string;
  children?: NavFileItem[];
}
