import { LocalLinter } from "../.bookinator/harper/node_modules/harper.js/dist/index.js";
import { binaryInlined } from "../.bookinator/harper/node_modules/harper.js/dist/binaryInlined.js";

let text = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) text += chunk;

const linter = new LocalLinter({ binary: binaryInlined });
const lints = await linter.lint(text, { language: "markdown", dedup: false });
const output = lints.map((lint) => {
  const span = lint.span();
  const suggestions = lint.suggestions().map((suggestion) => JSON.parse(suggestion.to_json()));
  const item = {
    start: span.start,
    end: span.end,
    kind: lint.lint_kind_pretty(),
    message: lint.message(),
    problemText: lint.get_problem_text(),
    suggestions,
  };
  span.free();
  lint.free();
  return item;
});
await linter.dispose();
process.stdout.write(JSON.stringify(output));
