<!DOCTYPE html>
<html lang="es">
    <head>
        <title>Productos</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/js/bootstrap.bundle.min.js"></script>
    </head>
    <body>
        <!-- NAVBAR (igual al resto del sitio) -->
        <nav class="navbar navbar-expand-sm bg-dark navbar-dark">
            <div class="container-fluid">
                <a class="navbar-brand" href="index.php">MiEmpresa</a>
                <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#collapsibleNavbar">
                    <span class="navbar-toggler-icon"></span>
                </button>
                <div class="collapse navbar-collapse" id="collapsibleNavbar">
                    <ul class="navbar-nav">
                        <li class="nav-item"><a class="nav-link" href="index.php">Inicio</a></li>
                        <li class="nav-item"><a class="nav-link active" href="productos.php">Productos</a></li>
                        <li class="nav-item"><a class="nav-link" href="servicios.php">Servicios</a></li>
                        <li class="nav-item"><a class="nav-link" href="contacto.php">Contacto</a></li>
                    </ul>
                </div>
            </div>
        </nav>

        <!-- CONTAINER -->
        <div class="container bg-light p-5 my-5 border">
            <h3>Productos</h3>

            <div class="mb-3">
                <label for="cmbProducto" class="form-label">Lista de productos:</label>
                <select id="cmbProducto" name="cmbProducto" class="form-select"></select>
            </div>

            <hr>

            <h5>Agregar producto</h5>
            <div class="row g-2 align-items-end">
                <div class="col-auto">
                    <label for="txtId" class="form-label">ID</label>
                    <input id="txtId" type="text" class="form-control">
                </div>
                <div class="col-auto">
                    <label for="txtNombre" class="form-label">Nombre</label>
                    <input id="txtNombre" type="text" class="form-control">
                </div>
                <div class="col-auto">
                    <label for="txtPrecio" class="form-label">Precio</label>
                    <input id="txtPrecio" type="text" class="form-control">
                </div>
                <div class="col-auto">
                    <button type="button" class="btn btn-primary" onclick="agregarProducto();">Agregar</button>
                </div>
            </div>
        </div>

        <!-- FOOTER -->
        <div class="container-fluid bg-dark">
            <div class="row p-3">
                <div class="col-4"></div>
                <div class="col-4 d-flex justify-content-center" style="color: rgb(255, 255, 255)">
                    <strong>Soporte24hrs@gmail.com</strong>
                </div>
                <div class="col-4"></div>
            </div>
        </div>

        <script>
           
            const respuestaAPI = {
                "status": 200,
                "message": "Productos obtenidos correctamente",
                "data": [
                    { "id": 1, "nombre": "Teclado", "precio": 4590 },
                    { "id": 2, "nombre": "Mouse",   "precio": 6000 }
                ]
            };

            // Poblamos el <select> con las opciones que vienen de la "API"
            function cargarProductosIniciales() {
                const cmb = document.getElementById("cmbProducto");
                respuestaAPI.data.forEach((producto) => {
                    const opt = document.createElement("option");
                    opt.setAttribute("value", producto.id);
                    opt.innerText = `${producto.nombre} - $${producto.precio}`;
                    cmb.appendChild(opt);
                });
            }

                const cmb = document.getElementById("cmbProducto");
                const id = document.getElementById("txtId").value;
                const nombre = document.getElementById("txtNombre").value;
                const precio = document.getElementById("txtPrecio").value;

                if (!id || !nombre) {
                    alert("Debes ingresar al menos ID y Nombre.");
                    return;
                }

                const opt = document.createElement("option");
                opt.setAttribute("value", id);
                opt.innerText = precio ? `${nombre} - $${precio}` : nombre;
                cmb.appendChild(opt);

                // Limpiamos los inputs después de agregar
                document.getElementById("txtId").value = "";
                document.getElementById("txtNombre").value = "";
                document.getElementById("txtPrecio").value = "";
            }

            document.addEventListener("DOMContentLoaded", cargarProductosIniciales);
        </script>
    </body>
</html>