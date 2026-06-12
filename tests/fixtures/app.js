// Frontend JS — DOM selector references

const app = document.getElementById("app");
const header = document.querySelector("#header");
const navLinks = document.querySelectorAll(".nav-link");
const searchInput = document.getElementById("search-input");
const searchForm = document.querySelector("#search-form");
const searchBtn = document.querySelector("#search-btn");

// jQuery example
const footer = $(".footer");
const footerText = $(".footer-text");

// Event handlers
searchBtn.addEventListener("click", function() {
    const query = searchInput.value;
    handleSearch(query);
});

function handleSearch(query) {
    const results = fetchResults(query);
    renderResults(results);
}

function fetchResults(query) {
    return fetch(`/api/search?q=${query}`).then(r => r.json());
}

function renderResults(data) {
    const container = document.querySelector(".content");
    container.innerHTML = data.map(item => `<div class="result-item">${item.name}</div>`).join("");
}

// Class list operations (should be ignored by parser)
document.body.classList.add("loading");
document.body.classList.remove("loading");
