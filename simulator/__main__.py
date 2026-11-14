"""CLI del simulador (RF-01). TODO Persona A."""
import argparse


def main():
    p = argparse.ArgumentParser(description="Simulador de flota ArquiFusion")
    p.add_argument("--api-url", required=True)
    p.add_argument("--api-key", required=True)
    p.add_argument("--scenario", default="normal",
                   choices=["normal", "degradacion", "falla_subita", "combustible", "grupal_zona", "ociosa"])
    p.add_argument("--machine")
    p.add_argument("--history")
    args = p.parse_args()
    raise NotImplementedError(f"TODO: escenario {args.scenario}")


if __name__ == "__main__":
    main()
