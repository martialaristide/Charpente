// Unified-diff parsing for the Git panel: files and hunks, and a patch for one hunk (block-by-block staging).

/** `git diff` text → [{header: [lines before the first hunk], path, hunks: [{header, lines}]}]. */
export function parseDiff(text) {
  const files = [];
  let file = null;
  let hunk = null;
  for (const line of String(text).split("\n")) {
    if (line.startsWith("diff --git ")) {
      file = { header: [line], path: pathOf(line), hunks: [] };
      files.push(file);
      hunk = null;
    } else if (!file) {
      continue;
    } else if (line.startsWith("@@")) {
      hunk = { header: line, lines: [] };
      file.hunks.push(hunk);
    } else if (hunk) {
      if (line === "\\ No newline at end of file" || /^[ +\-]/.test(line)) hunk.lines.push(line);
    } else {
      file.header.push(line);
    }
  }
  for (const f of files) {
    const target = f.header.find((l) => l.startsWith("+++ "));
    if (target && target !== "+++ /dev/null") f.path = target.slice(4).replace(/^b\//, "");
  }
  return files;
}

function pathOf(diffLine) {
  const match = / b\/(.+)$/.exec(diffLine);
  return match ? match[1] : diffLine.slice(11);
}

/** A patch that applies just `hunk` of `file` (what `git apply --cached` wants). */
export function hunkPatch(file, hunk) {
  return [...file.header, hunk.header, ...hunk.lines].join("\n") + "\n";
}

export function hunkStats(hunk) {
  let added = 0;
  let removed = 0;
  for (const line of hunk.lines) {
    if (line.startsWith("+")) added++;
    else if (line.startsWith("-")) removed++;
  }
  return { added, removed };
}
