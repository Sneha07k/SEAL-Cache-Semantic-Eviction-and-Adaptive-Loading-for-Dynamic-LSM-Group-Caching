# SEAL-Cache

## Adaptive Group Caching for Dynamic LSM-Based Storage Engines

SEAL-Cache is an experimental systems research project that investigates adaptive caching for dynamic LSM-based key-value storage engines.

The project builds a simplified LSM storage simulator and compares three caching approaches:

- Traditional Cache
- Group Cache
- SEAL-Cache

---

## Problem Statement

LSM-based key-value stores provide efficient write performance, but maintaining effective caching becomes challenging under dynamic workloads.

Existing Group Cache approaches improve caching by storing logically related key-value data as groups. However, frequent writes, MemTable flushes, and compactions can reorganize the underlying storage and affect the usefulness of previously cached groups.

SEAL-Cache investigates whether cache management can adapt to these changes.

---

## Our Approach

SEAL-Cache extends group-based caching by considering:

- Data access behavior
- Update activity
- LSM structural changes
- Optional semantic or application-level context

Instead of immediately evicting a cached group whenever it is affected by changes, SEAL-Cache marks moderately affected groups for reassessment.

During reassessment, the system determines whether the group should be:

- **Kept**
- **Rebuilt**
- **Replaced or Evicted**

> A cached group should not be considered permanently useful simply because it was useful in the past. Cache decisions should adapt when the underlying storage changes.

---

## System Overview

<img width="3812" height="5062" alt="seal_cache_architecture (1)" src="https://github.com/user-attachments/assets/6464a26f-7ad3-4324-8e8b-aaae4635209a" />
