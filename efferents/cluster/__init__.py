"""Hosted multi-owner lab cluster: one server, many labs, many participants.

A cluster is a directory that owns a registry, participant identities,
executor tracks, the labs created from them, and the shared journal that
lets those labs read and review each other. The web server, the keeper
(supervision + caps) and the sync job (shared journal + cross-lab reviews)
are separate processes over the same files.
"""
