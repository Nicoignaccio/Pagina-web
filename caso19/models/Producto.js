const mongoose = require('mongoose');

const productoSchema = mongoose.Schema({
  nombre: String,
  categoria: String,
  precio: Number,
  disponible: Boolean
});

module.exports = mongoose.model('Producto', productoSchema);