// Browser page translators (Chrome/Edge "Translate", extensions) replace text
// nodes with their own elements. React 18 then fails when it later removes or
// inserts next to a node that is no longer where it left it, and the whole
// page goes blank. These guards turn that failure into a no-op; the remaining
// effect is that a translated phrase may lag behind an update, which the
// translator corrects when it re-translates the changed element.
// (Workaround described in https://github.com/facebook/react/issues/11538.)

export function guardAgainstTranslatorMutations(): void {
  if (typeof Node !== "function" || !Node.prototype) return;
  const removeChild = Node.prototype.removeChild;
  Node.prototype.removeChild = function <T extends Node>(this: Node, child: T): T {
    if (child.parentNode !== this) return child;
    return removeChild.call(this, child) as T;
  };
  const insertBefore = Node.prototype.insertBefore;
  Node.prototype.insertBefore = function <T extends Node>(this: Node, node: T, ref: Node | null): T {
    if (ref && ref.parentNode !== this) return insertBefore.call(this, node, null) as T;
    return insertBefore.call(this, node, ref) as T;
  };
}
