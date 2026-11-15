// @vitest-environment jsdom
/**
 * Regresión del robo de foco del `Modal`.
 *
 * `onClose` suele pasarse como flecha inline (`() => setOpen(false)`), así que cambia de identidad en
 * cada render del padre. Cuando el efecto de foco dependía de `onClose`, se volvía a ejecutar en cada
 * render (p. ej. con el tick de 1 s del modo demo) y devolvía el foco al primer campo del cuerpo,
 * cerrando cualquier <select> que el usuario tuviera abierto. Ver el arreglo (onClose en un ref) en
 * Modal.tsx.
 */
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Modal } from "./Modal";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.body.style.overflow = "";
});

// Cuerpo con dos campos: el foco inicial debe caer en el primero (input).
const body = createElement(
  "div",
  null,
  createElement("input", { id: "campo-nombre" }),
  createElement("select", { id: "campo-zona" }, createElement("option", { value: "z" }, "z")),
);

function render(open: boolean, onClose: () => void, children = body) {
  act(() => {
    root.render(createElement(Modal, { title: "Título", open, onClose, children }));
  });
}

describe("Modal · foco (regresión del robo de foco / cierre de <select>)", () => {
  it("al abrir enfoca el primer campo del cuerpo", () => {
    render(true, () => {});
    expect(document.activeElement).toBe(document.getElementById("campo-nombre"));
  });

  it("sin campos en el cuerpo, el foco inicial cae en el botón Cerrar", () => {
    render(true, () => {}, createElement("p", null, "texto sin campos"));
    expect((document.activeElement as HTMLElement | null)?.getAttribute("aria-label")).toBe("Cerrar");
  });

  it("re-render con un onClose nuevo NO roba el foco (no cierra los <select>)", () => {
    render(true, () => {});
    const select = document.getElementById("campo-zona") as HTMLSelectElement;

    act(() => select.focus());
    expect(document.activeElement).toBe(select);

    // El padre se re-renderiza con otra identidad de `onClose`, igual que en cada tick de 1 s.
    render(true, () => {});

    expect(document.activeElement).toBe(select);
  });

  it("Escape invoca el último onClose recibido (ref, no el del primer render)", () => {
    const first = vi.fn();
    const second = vi.fn();
    render(true, first);
    render(true, second);

    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });

    expect(second).toHaveBeenCalledTimes(1);
    expect(first).not.toHaveBeenCalled();
  });
});
