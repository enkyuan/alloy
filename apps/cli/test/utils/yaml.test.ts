import { describe, expect, it } from "vitest";
import { parseYaml } from "../../src/utils/yaml.js";

describe("parseYaml", () => {
  it("parses block mappings and sequences", () => {
    const yaml = `paths:\n  /pets:\n    get:\n      operationId: listPets\n      tags:\n        - pets\n`;
    const out = parseYaml(yaml) as any;
    expect(out.paths["/pets"].get.operationId).toBe("listPets");
    expect(out.paths["/pets"].get.tags).toEqual(["pets"]);
  });

  it("handles quoted strings and comments", () => {
    const yaml = `title: "Pet API" # the name\nversion: '1.0'\n`;
    const out = parseYaml(yaml) as any;
    expect(out.title).toBe("Pet API");
    expect(out.version).toBe("1.0");
  });
});
