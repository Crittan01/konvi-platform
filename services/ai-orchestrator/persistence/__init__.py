"""Capa de persistencia del orquestador.

Cada repo aísla queries Supabase de la lógica de negocio. Reglas:
  - Toda query filtra por ``tenant_id`` explícito (service_role bypassa RLS).
  - Sin lógica de negocio dentro de los repos: solo I/O.
  - Excepciones tipadas (``CartNotFound``, ``CartConflict``, etc.) en lugar
    de ``except Exception`` genérico.
"""
