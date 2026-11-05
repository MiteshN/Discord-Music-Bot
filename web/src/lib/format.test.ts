import { describe, expect, it } from "vitest";
import { activeLine, formatLong, formatTime, initials, splitTitle, youtubeThumb } from "./format";

describe("formatTime", () => {
  it.each([
    [0, "0:00"],
    [59.9, "0:59"],
    [61, "1:01"],
    [3725, "1:02:05"],
    [-3, "0:00"],
  ])("%s -> %s", (input, out) => expect(formatTime(input)).toBe(out));
});

describe("formatLong", () => {
  it("rounds to minutes and hours", () => {
    expect(formatLong(30)).toBe("1 min");
    expect(formatLong(2520)).toBe("42 min");
    expect(formatLong(7500)).toBe("2 hr 5 min");
    expect(formatLong(7200)).toBe("2 hr");
  });
});

describe("splitTitle", () => {
  it("uses the known artist", () => {
    expect(splitTitle("Lumen Drive - Glass Harbor", "Lumen Drive")).toEqual({ name: "Glass Harbor", by: "Lumen Drive" });
  });
  it("splits a video title", () => {
    expect(splitTitle("Some Band - A Song (Live)")).toEqual({ name: "A Song (Live)", by: "Some Band" });
  });
  it("leaves plain titles alone", () => {
    expect(splitTitle("Just a title")).toEqual({ name: "Just a title", by: "" });
  });
});

describe("activeLine", () => {
  const lines = [0, 5, 10, 20].map((time) => ({ time, text: String(time) }));
  it("finds the line being sung", () => {
    expect(activeLine(lines, -1)).toBe(-1);
    expect(activeLine(lines, 0)).toBe(0);
    expect(activeLine(lines, 9.9)).toBe(1);
    expect(activeLine(lines, 99)).toBe(3);
    expect(activeLine([], 3)).toBe(-1);
  });
});

describe("helpers", () => {
  it("makes initials", () => expect(initials("lofi  lounge club 2")).toBe("LLC"));
  it("builds YouTube thumbnails", () => {
    expect(youtubeThumb("https://www.youtube.com/watch?v=dQw4w9WgXcQ")).toBe("https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg");
    expect(youtubeThumb("https://example.com")).toBe("");
  });
});
