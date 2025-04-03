# Storing and Using Tokens Locally - Data Flow Diagrams (DFD)

This document outlines the data flow for securely storing and using access/refresh tokens locally.

## 1. Storing Access/Refresh Tokens

The following sequence diagram illustrates the process of exchanging and securely storing access/refresh tokens:

```mermaid
sequenceDiagram
    title Token Exchange and Secure Storage

    participant Client
    participant Publisher
    participant OAuth2 Platform
    participant Vault

    Client ->>+ Publisher: ExchangeAndStore
    Note right of Client: `store_on_device: true` <br/> Indicates local storage preference
    Publisher ->>+ OAuth2 Platform: Exchange Authorization Code
    OAuth2 Platform -->>- Publisher: Return Access/Refresh Tokens
    Publisher ->>+ Vault: Store Token Metadata
    Note right of Publisher: Access/refresh tokens <br/> are removed
    Vault -->>- Publisher: Confirm Storage Success
    Publisher -->>- Client: Return Exchange Response
    Note left of Publisher: Response includes access/refresh tokens
```

### Summary:

1. **Client Request**: The client requests token exchange and storage.
2. **Token Exchange**: The Publisher exchanges the authorization code with the OAuth2 platform for tokens.
3. **Secure Storage**: Tokens metadata are stored in the Vault, and the access/refresh tokens are sent to the client.
4. **Response**: The Publisher confirms the operation to the client.

## 2. Publishing Content with Local Tokens

This sequence diagram details the process of publishing content using locally stored tokens, including token refresh handling:

```mermaid
sequenceDiagram
    title Content Publishing with Token Management

    participant Client
    participant Publisher
    participant OAuth2 Platform
    participant Vault

    Client ->>+ Publisher: PublishContent
    Note right of Client: Includes payload and access token
    Publisher ->>+ Vault: Retrieve Token Metadata
    Vault -->>- Publisher: Return Token Metadata
    alt Token Expired
        Publisher ->>+ OAuth2 Platform: Refresh Token
        OAuth2 Platform -->>- Publisher: Return Refreshed Tokens
        Publisher ->>+ Vault: Update Token Metadata
        Vault -->>- Publisher: Confirm Update
    end
    Publisher ->>+ OAuth2 Platform: Publish Message
    OAuth2 Platform -->>- Publisher: Return Publish Response
    Publisher --)- Client: Deliver SMS Response
    Note left of Publisher: If token was refreshed, <br/> user is prompted to go online <br/> to get new tokens.
```

### Summary:

1. **Client Request**: The client sends a request to publish content, including the payload and access token.
2. **Token Retrieval**: The Publisher retrieves token metadata from the Vault.
3. **Token Refresh (if needed)**: If the token is expired, the Publisher refreshes it with the OAuth2 platform and updates the Vault.
4. **Content Publishing**: The Publisher uses the valid token to publish the message.
5. **Response**: The Publisher delivers the SMS response to the client. If token was refreshed, the user is prompted to go online and get new tokens.
