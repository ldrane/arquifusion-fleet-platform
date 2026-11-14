"""Seeds de datos maestros (§5.6). Idempotente: se puede correr varias veces. TODO Persona C.

IDs según contratos.md §1: máquinas EX-023, técnicos TEC-07, almacenes WH-01, componentes CMP-014.
"""
import argparse


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", required=True)
    p.parse_args()
    raise NotImplementedError


if __name__ == "__main__":
    main()
