# Adapter Architecture – Data Flow

This document describes the architecture and data flow between Publisher and Platform Adapters in RelaySMS-Publisher.

---

## 1. System Architecture

### Overview

High-level architecture:

```mermaid
flowchart LR
    %% Main Components
    Client[Client Application]

    subgraph Publisher[Publisher]
        GRPC[gRPC Server]
        AM[Adapter Manager]
        IPC[IPC Handler]
        Registry[(Adapter Registry)]
    end

    subgraph Interfaces[Protocol Interfaces]
        BasePI[Base Interface]
        OAuth2PI[OAuth2]
        PNBAPI[PNBA]
        EventPI[Event]
    end

    subgraph Adapters[Platform Adapters]
        PlatformAdapters[Adapters]
    end

    subgraph Platforms[External Platforms]
        APIs[Platform APIs]
    end

    %% Flow connections
    Client --> GRPC
    GRPC --> AM
    AM --> Registry
    AM --> IPC
    IPC --> PlatformAdapters
    PlatformAdapters --> APIs
    PlatformAdapters --> IPC
    IPC --> AM
    AM --> GRPC
    GRPC --> Client

    PlatformAdapters -.->|implements| Interfaces
    AM -.->|uses| Interfaces
```

---

## 2. Data Flow

Data flow through the system:

```mermaid
sequenceDiagram
    participant Client
    participant gRPC as Publisher.gRPC
    participant AM as AdapterManager
    participant Registry
    participant IPC
    participant Adapter
    participant Platform

    Client->>gRPC: Send message request
    gRPC->>AM: Forward request

    alt Adapter not in registry
        AM->>Registry: Check registry
        Registry->>AM: Not found
        AM->>AM: Discover and register adapter
    end

    AM->>Registry: Get adapter info
    AM->>IPC: Launch adapter
    IPC->>Adapter: Start isolated process

    Adapter->>Platform: Send message
    Platform->>Adapter: Return response

    Adapter->>IPC: Send result
    IPC->>AM: Forward result
    AM->>gRPC: Return processed response
    gRPC->>Client: Return final response
```

---

## 3. Protocol Interfaces

Protocol Interfaces define contracts for platform interactions. Adapters implement these interfaces to enable communication with various platforms through a consistent approach.

Interface types:

- **Base Interface**: Core methods for configuration and manifest retrieval.
- **OAuth2**: Authorization flow and token management for OAuth2 platforms.
- **PNBA** (Phone Number Based Authentication): Code validation and messaging for PNBA platforms.
- **Event**: CRUD operations for event-driven platforms.

---

## 4. Components

### Publisher

- **gRPC Server**: Entry point for client requests.
- **Adapter Manager**: Manages adapter selection, discovery, and lifecycle.
- **IPC Handler**: Handles inter-process communication using JSON over pipes.
- **Adapter Registry**: Stores adapter metadata.

### Platform Adapters

- **Adapters**: Modular components implementing protocol interfaces for specific platforms (Gmail, Twitter, Telegram, etc.).

---

## 5. Data Flow Summary

1. Client sends message request to gRPC server.
2. Request is forwarded to Adapter Manager.
3. Adapter Manager checks registry for appropriate adapter.
4. If needed, adapter is discovered and registered.
5. IPC Handler launches adapter in isolated environment.
6. Adapter communicates with external platform.
7. Response flows back through system to client.
