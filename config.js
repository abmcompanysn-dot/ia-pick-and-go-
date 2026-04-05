/**
 * Configuration globale DALL JAMM
 */
const CONFIG = {
    // Remplacez par l'IP de votre serveur (ex: 192.168.1.11)
    // Si vide, utilise l'IP stockée en localstorage
    SERVER_IP: localStorage.getItem('hyflex_server') || window.location.hostname,
    SERVER_PORT: "8000",
    API_BASE: (ip) => `https://${ip}:8000`,
    PROJECT_NAME: "DALL JAMM"
};