"""Optional Ren’Py adapter. The engine is imported only when installing it."""

from .runtime import LogicDB, RuleError


class RenpyLogicDB(LogicDB):
    """A LogicDB with Ren’Py save/load, rollback and development callbacks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._renpy_binding = None

    def install_renpy(self, config, snapshot_variable="logic_snapshot", *, watch_rules=False):
        """Bind once in init python; declare the snapshot with `default` in .rpy."""
        self._idle()
        binding = (config, snapshot_variable, watch_rules)
        if self._renpy_binding is not None:
            if self._renpy_binding == binding:
                return
            raise RuntimeError("LogicDB is already bound to a different Ren'Py configuration")
        if watch_rules and self._path is None:
            raise ValueError("Rule watching requires a source path")
        if self._on_snapshot is not None:
            raise ValueError("A snapshot sink is already configured")
        import renpy

        def write_snapshot(value):
            setattr(renpy.store, snapshot_variable, value)

        def after_defaults():
            self.restore(getattr(renpy.store, snapshot_variable, None))

        last_error = None

        def watch():
            nonlocal last_error
            if not config.developer or self._path is None:
                return
            try:
                self.reload_if_changed()
                last_error = None
            except (RuleError, OSError) as exc:
                if str(exc) != last_error:
                    renpy.exports.log(f"Ren'Py Relations: reload failed: {exc}")
                    renpy.exports.notify("Rule reload failed; previous rules remain active. See log.txt.")
                    last_error = str(exc)

        self.snapshot()
        self._on_snapshot = write_snapshot
        config.after_default_callbacks.append(after_defaults)
        if watch_rules:
            config.interact_callbacks.append(watch)
        self._renpy_binding = binding
