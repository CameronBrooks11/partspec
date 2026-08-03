"""Engine adapters: turn a source reference into an artifact.

Each module here shells out to or drives one CAD engine. Imports of the engines
themselves are local to the functions that need them, so that importing
`partspec` stays free of CAD dependencies (SPEC-contract.md 1.1).
"""
