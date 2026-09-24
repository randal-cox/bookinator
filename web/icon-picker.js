export function graphemes(value) {
  const text = String(value || "");
  if (typeof Intl.Segmenter === "function") {
    return [...new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(text)].map(({ segment }) => segment);
  }
  return Array.from(text);
}

export function shortMark(value, maximumGraphemes = 3) {
  return graphemes(value).slice(0, maximumGraphemes).join("");
}

export function unicodeIcon(value) {
  const mark = shortMark(value);
  return mark ? { kind: "unicode", value: mark, background: "#071f4a", outline: true } : null;
}

export function fallbackIcon(title) {
  return unicodeIcon(shortMark(String(title || "B").trim(), 1).toLocaleUpperCase()) || unicodeIcon("B");
}

export function renderIcon(element, icon, fallback = "B") {
  if (!element) return;
  element.replaceChildren();
  const resolved = icon?.value ? icon : fallbackIcon(fallback);
  element.dataset.iconKind = resolved.kind;
  const background = /^#[0-9a-f]{6}$/i.test(resolved.background || "") ? resolved.background : "#071f4a";
  const rgb = [1, 3, 5].map((offset) => Number.parseInt(background.slice(offset, offset + 2), 16));
  const luminance = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
  element.style.setProperty("--icon-background", background);
  element.style.setProperty("--icon-foreground", luminance > 0.62 ? "#10213d" : "#ffffff");
  element.classList.toggle("without-book-outline", resolved.outline === false);
  const face = document.createElement("span");
  face.className = "book-icon-face";
  if (resolved.kind === "image") {
    const image = document.createElement("img");
    image.src = resolved.value;
    image.alt = "";
    face.append(image);
    element.append(face);
    return;
  }
  const value = shortMark(resolved.value) || "B";
  element.dataset.graphemes = String(graphemes(value).length);
  face.textContent = value;
  element.append(face);
}

export async function imageFileToIcon(file, size = 256) {
  if (!file?.type?.startsWith("image/")) throw new Error("Choose an image file.");
  const source = await createImageBitmap(file);
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  const scale = Math.min(size / source.width, size / source.height);
  const width = source.width * scale;
  const height = source.height * scale;
  context.drawImage(source, (size - width) / 2, (size - height) / 2, width, height);
  source.close?.();
  return { kind: "image", value: canvas.toDataURL("image/webp", 0.84), width: size, height: size, background: "#071f4a", outline: false };
}
