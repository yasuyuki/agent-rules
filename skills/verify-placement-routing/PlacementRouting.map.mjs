const where = (s) => (s === "windows-controller" ? "Session on windows-controller" : "Session on ubuntu-26-development");
const left = (v) => v.targets.filter((e) => !v.applied.includes(e)).sort().join(", ");
export const title = "Multi-environment skill update";
export const state = (v) => {
  if (v.editedAt === "none") return [where(v.session), "Source not edited"];
  if (v.editedAt === "windows-controller") return [where(v.session), "Source edited on the controller"];
  if (!v.integrated) return [where(v.session), "Source edited on ubuntu-26-development"];
  const rest = left(v);
  return [where(v.session), rest ? `Pushed, still to place: ${rest}` : "Placed in every target"];
};
export const step = (a, f, t) => {
  if (a === "EditHere") return "the session edits the task checkout";
  if (a === "Delegate") return "the controller delegates the source work";
  if (a === "EditOnController") return "the controller edits its own checkout";
  if (a === "Integrate") return "lifecycle finish pushes to GitHub";
  if (a === "Apply") {
    const e = t.applied.find((x) => !f.applied.includes(x));
    return `apply, check and reapply on ${e}`;
  }
  return null;
};
export const group = (v) => (v.session === "windows-controller" ? "controller" : "development");
export const colors = { controller: "blue", development: "orange" };
