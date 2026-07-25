import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { diagramConnectorMarkup } from "./diagram";

describe("diagramConnectorMarkup", () => {
  it("constrains every down arrow to one diagram column", () => {
    assert.equal(
      diagramConnectorMarkup("  \u25bc   \u25bc"),
      '  <span class="diagram-arrow">\u25bc</span>   <span class="diagram-arrow">\u25bc</span>',
    );
  });

  it("escapes connector copy without changing box-drawing glyphs", () => {
    assert.equal(diagramConnectorMarkup("\u2502 events < tools"), "\u2502 events &lt; tools");
  });
});
