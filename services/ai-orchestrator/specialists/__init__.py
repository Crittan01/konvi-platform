"""Specialists — uno por estado del FSM.

Cada specialist es una **función pura** que recibe :class:`ConversationContext`
y devuelve :class:`TurnResult` declarativo.

Patrón Functional Core / Imperative Shell (Bernhardt). Los specialists no
hacen I/O directo: el coordinator les inyecta repos y los ejecuta. Esto los
hace 100% testeables sin DB ni red.

Mapping estado → specialist en :mod:`core.coordinator.SPECIALISTS`.
"""
