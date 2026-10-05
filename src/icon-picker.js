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

export function coverAuthorName(author) {
  const words = String(author || "").trim().replace(/^by\s+/i, "").split(/\s+/).filter(Boolean);
  if (!words.length || String(author).trim().toLocaleLowerCase() === "author not specified") return "";
  return words.join(" ");
}

function relativeLuminance(rgb) {
  const channels = rgb.map((channel) => {
    const value = channel / 255;
    return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
  });
  return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2];
}

export function iconTextAppearance(background) {
  const color = /^#[0-9a-f]{6}$/i.test(background || "") ? background : "#071f4a";
  const rgb = [1, 3, 5].map((offset) => Number.parseInt(color.slice(offset, offset + 2), 16));
  const backgroundLuminance = relativeLuminance(rgb);
  const dark = [16, 33, 61];
  const darkLuminance = relativeLuminance(dark);
  const lightContrast = 1.05 / (backgroundLuminance + .05);
  const darkContrast = (backgroundLuminance + .05) / (darkLuminance + .05);
  const foreground = darkContrast > lightContrast ? "#10213d" : "#ffffff";
  return {foreground, shadow: foreground === "#ffffff" ? "0 1px 2px rgb(0 0 0 / 72%)" : "none"};
}

function fitBookMetadata(element, spine, byline) {
  requestAnimationFrame(() => {
    const largePreview = element.classList.contains("book-mark-preview");
    const fit = (label, maximum, height, minimum = 2) => {
      let size = maximum;
      label.style.fontSize = `${size}px`;
      while (size > minimum && (label.scrollWidth > label.clientWidth + .5 || label.scrollHeight > height + .5)) {
        size -= .25;
        label.style.fontSize = `${size}px`;
      }
    };
    fit(spine, Math.min(largePreview ? 10 : 7, element.clientWidth * .09), Math.max(8, element.clientHeight - 6));
    if (byline) {
      const intendedSize = Number.parseFloat(getComputedStyle(byline).fontSize) || 5;
      fit(byline, Math.min(largePreview ? 10 : 8, intendedSize), Math.max(8, element.clientHeight * .3), largePreview ? 8 : 7);
    }
  });
}

export function renderIcon(element, icon, fallback = "B", author = "") {
  if (!element) return;
  element.replaceChildren();
  const resolved = icon?.value ? icon : fallbackIcon(fallback);
  element.dataset.iconKind = resolved.kind;
  const background = /^#[0-9a-f]{6}$/i.test(resolved.background || "") ? resolved.background : "#071f4a";
  const textAppearance = iconTextAppearance(background);
  element.style.setProperty("--icon-background", background);
  element.style.setProperty("--icon-foreground", textAppearance.foreground);
  element.style.setProperty("--icon-text-shadow", textAppearance.shadow);
  element.classList.toggle("without-book-outline", resolved.outline === false);
  const face = document.createElement("span");
  face.className = "book-icon-face";
  if (resolved.kind === "image") {
    const image = document.createElement("img");
    image.src = resolved.value;
    image.alt = "";
    face.append(image);
    element.append(face);
    const coverAuthor = coverAuthorName(author);
    if (resolved.outline !== false && coverAuthor) {
      element.classList.add("has-cover-metadata");
      const spine = document.createElement("span");
      spine.className = "book-spine-title";
      spine.textContent = String(fallback || "Untitled");
      spine.title = String(fallback || "Untitled");
      const byline = document.createElement("span");
      byline.className = "book-cover-author";
      const authorParts = coverAuthor.split(/\s+/);
      if (authorParts.length > 1) {
        byline.append(document.createTextNode(authorParts.slice(0, -1).join(" ")), document.createElement("br"), document.createTextNode(authorParts.at(-1)));
      } else {
        byline.textContent = coverAuthor;
      }
      byline.title = String(author || "");
      element.append(spine, byline);
      fitBookMetadata(element, spine, byline);
    } else {
      element.classList.remove("has-cover-metadata");
    }
    return;
  }
  element.classList.remove("has-cover-metadata");
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
