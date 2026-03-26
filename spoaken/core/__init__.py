"""
Spoaken — Voice-to-Text Engine
================================
Package root.

Do NOT place heavy imports here.  Importing controller, engine, or gui at
package-init time triggers the full model-loading chain before the venv
guard and splash screen have run, causing crashes when config.py or any
model package is absent.

Import sub-modules directly where needed, e.g.:
    from spoaken.control.controller import TranscriptionController
    from spoaken.ui.gui import TranscriptionView
"""
