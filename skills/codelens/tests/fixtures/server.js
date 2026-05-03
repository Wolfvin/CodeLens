// Backend JS — function call graph

const express = require("express");
const app = express();

function initializeApp(config) {
    setupMiddleware(config);
    setupRoutes(config);
    startServer(config.port);
}

function setupMiddleware(config) {
    app.use(express.json());
    app.use(corsMiddleware(config));
}

function setupRoutes(config) {
    app.get("/api/health", healthCheck);
    app.post("/api/users", createUser);
    app.get("/api/users/:id", getUser);
}

function startServer(port) {
    app.listen(port, () => {
        console.log(`Server running on port ${port}`);
    });
}

async function healthCheck(req, res) {
    res.json({ status: "ok" });
}

async function createUser(req, res) {
    const validated = validateInput(req.body);
    const hashed = hashPassword(validated.password);
    const user = await saveUser({ ...validated, password: hashed });
    res.json(user);
}

async function getUser(req, res) {
    const user = await findUser(req.params.id);
    if (!user) {
        return res.status(404).json({ error: "Not found" });
    }
    res.json(user);
}

function validateInput(data) {
    if (!data.email || !data.password) {
        throw new Error("Missing fields");
    }
    return data;
}

function hashPassword(password) {
    return crypto.createHash("sha256").update(password).digest("hex");
}

async function saveUser(user) {
    return db.insert("users", user);
}

async function findUser(id) {
    return db.findById("users", id);
}

function corsMiddleware(config) {
    return (req, res, next) => {
        res.setHeader("Access-Control-Allow-Origin", config.allowedOrigin || "*");
        next();
    };
}

initializeApp({ port: 3000, allowedOrigin: "http://localhost:3000" });
