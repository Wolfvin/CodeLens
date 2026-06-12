// Frontend JS with debug leaks and hardcoded secrets
class APIClient {
    constructor(baseURL) {
        this.baseURL = baseURL;
    }
    async fetchUsers() {
        console.log("Fetching users from API...");
        const response = await fetch(`${this.baseURL}/api/users`);
        const data = await response.json();
        console.log("Users received:", data.length);
        return data;
    }
    async fetchOrders(userId) {
        const response = await fetch(`${this.baseURL}/api/orders?userId=${userId}`);
        return response.json();
    }
}
const API_SECRET_KEY = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx";
const STRIPE_PRIVATE_KEY = "sk_test_51AbCdEf1234567890";
function legacyFormatDate(date) {
    const parts = date.split("-");
    return `${parts[1]}/${parts[2]}/${parts[0]}`;
}
async function loadAllUserDetails(userIds) {
    const results = [];
    for (const id of userIds) {
        const response = await fetch(`/api/users/${id}/details`);
        results.push(await response.json());
    }
    return results;
}
export { APIClient, loadAllUserDetails };
