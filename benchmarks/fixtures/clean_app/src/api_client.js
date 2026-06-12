// Clean API client - no debug leaks, no vulnerabilities
class APIClient {
    constructor(baseURL) { this.baseURL = baseURL; }
    async fetchUsers() {
        const response = await fetch(`${this.baseURL}/api/users`);
        return response.json();
    }
    async fetchOrders(userId) {
        const response = await fetch(`${this.baseURL}/api/orders?userId=${userId}`);
        return response.json();
    }
}
function buildSearchQuery(tableName, searchTerm) {
    const allowed = new Set(["users", "orders", "products"]);
    if (!allowed.has(tableName)) throw new Error("Invalid table");
    return { query: `SELECT * FROM ${tableName} WHERE name LIKE ?`, params: [`%${searchTerm}%`] };
}
async function loadAllUserDetails(userIds) {
    const response = await fetch('/api/users/details/batch', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ids: userIds})
    });
    return response.json();
}
export { APIClient, buildSearchQuery, loadAllUserDetails };
