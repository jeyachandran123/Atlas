"""
Database-specific prompt modules.
"""

from __future__ import annotations

POSTGRESQL = """\
PostgreSQL expertise: query optimization (EXPLAIN ANALYZE), indexes \
(B-tree, GIN, GiST, partial), CTEs, window functions, JSONB operations, \
full-text search, partitioning, connection pooling (PgBouncer), \
and replication strategies."""

MYSQL = """\
MySQL expertise: InnoDB engine, index optimization, query profiling, \
stored procedures, replication (binlog), \
and MySQL 8+ window functions and CTEs."""

MSSQL = """\
SQL Server expertise: execution plans, columnstore indexes, \
Always On Availability Groups, T-SQL optimization, \
temporal tables, and Azure SQL integration."""

MONGODB = """\
MongoDB expertise: aggregation pipeline, indexes (compound, text, geospatial), \
schema design (embedding vs referencing), change streams, \
transactions, and Atlas Search."""

REDIS = """\
Redis expertise: data structures (strings, hashes, lists, sets, sorted sets, \
streams), pub/sub, Lua scripting, Redis Cluster, \
Sentinel, and cache invalidation strategies."""

ELASTICSEARCH = """\
Elasticsearch expertise: mapping, analyzers, query DSL, \
aggregations, index lifecycle management, \
and relevance tuning."""

DYNAMODB = """\
DynamoDB expertise: single-table design, partition key selection, \
GSI/LSI design, DynamoDB Streams, \
and cost optimization patterns."""

FIREBASE_DB = """\
Firebase expertise: Firestore data modeling, security rules, \
real-time listeners, offline persistence, \
and Firebase Admin SDK."""

SQL_GENERAL = """\
SQL expertise: normalization (1NF-3NF-BCNF), JOIN optimization, \
subqueries vs CTEs, window functions, \
transaction isolation levels, and index design principles."""
