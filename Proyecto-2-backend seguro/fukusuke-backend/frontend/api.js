// Cliente del API Gateway para el frontend. NO contiene secretos: solo la URL pública del gateway y el token de sesión.
const API_BASE = window.FUKUSUKE_API || "http://127.0.0.1:8000/api/v1";
let token = sessionStorage.getItem("fk_token");

async function request(method, path, body) {
  const res = await fetch(API_BASE + path, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.detail || "Error " + res.status), { status: res.status });
  return data;
}

export const api = {
  async login(username, password) {
    const d = await request("POST", "/auth/login", { username, password });
    token = d.access_token; sessionStorage.setItem("fk_token", token);
  },
  async logout() { await request("POST", "/auth/logout"); token = null; sessionStorage.removeItem("fk_token"); },
  register: (username, password) => request("POST", "/auth/register", { username, password }),
  productos: (soloDisponibles = true) => request("GET", "/products?available=" + soloDisponibles),
  miPerfil: () => request("GET", "/clients/me"),
  guardarPerfil: (perfil) => request("PUT", "/clients/me", perfil),
  // El navegador envía solo ids y cantidades; precios, total y estado los calcula el servidor.
  crearPedido: (items) => request("POST", "/orders", { items }),
  anularPedido: (id) => request("DELETE", "/orders/" + id),
  iniciarPago: (orderId) => request("POST", "/payments", { order_id: orderId }),
  resumenPedido: (id) => request("POST", "/graphql", {
    query: "query($id:Int!){ resumenPedido(id:$id){ id estado total direccionEntrega pagoEstado detalleDegradado items{ nombre cantidad subtotal categoria descripcion } } }",
    variables: { id },
  }).then((r) => { if (r.errors) throw new Error(r.errors[0].message); return r.data.resumenPedido; }),
};
