def changes(feed):
    """Subscribe to committed changes; clients resync after every reconnect."""
    return feed.stream()
