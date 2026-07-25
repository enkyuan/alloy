import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { activeTocIndex, tocActivationLine } from "./toc";

describe("tocActivationLine", () => {
  test("uses a restrained reading line across viewport sizes", () => {
    assert.equal(tocActivationLine(320, 0, 2000), 96);
    assert.equal(tocActivationLine(720, 0, 2000), 180);
    assert.equal(tocActivationLine(1600, 0, 3000), 240);
    assert.equal(tocActivationLine(50, 0, 100), 50);
  });

  test("expands through the remaining viewport near the page end", () => {
    assert.equal(tocActivationLine(720, 2557, 3097), 180);
    assert.equal(Math.round(tocActivationLine(720, 2900, 3097)), 523);
    assert.equal(tocActivationLine(720, 3097, 3097), 720);
  });
});

describe("activeTocIndex", () => {
  test("returns no selection without headings", () => {
    assert.equal(activeTocIndex([], 720, 0, 1000), -1);
  });

  test("keeps the first heading active at the top of the page", () => {
    assert.equal(activeTocIndex([257, 479, 1647], 720, 0, 3097), 0);
  });

  test("advances at the reading line without skipping short sections", () => {
    assert.equal(activeTocIndex([120, 181, 242], 720, 400, 2000), 0);
    assert.equal(activeTocIndex([119, 180, 241], 720, 401, 2000), 1);
    assert.equal(activeTocIndex([58, 119, 180], 720, 462, 2000), 2);
  });

  test("selects the final heading when the page cannot scroll it to the reading line", () => {
    assert.equal(activeTocIndex([-2900, -500, 386], 720, 3097, 3097), 2);
  });

  test("selects each short tail section before the final heading", () => {
    assert.equal(activeTocIndex([-2643, -170, 409, 583], 720, 2900, 3097), 2);
    assert.equal(activeTocIndex([-2743, -270, 309, 483], 720, 3000, 3097), 3);
  });

  test("uses the first heading on a non-scrolling page", () => {
    assert.equal(activeTocIndex([120, 240], 720, 0, 0), 0);
  });
});
