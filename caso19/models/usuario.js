const mongoose = require('mongoose');

const usuarioSchema = mongoose.Schema({
  nombre: String,
  email: String,
  password: String,
  rol: {
    type: String,
    enum: ['administrador', 'cajero_virtual', 'encargado_despacho', 'dueño'],
    required: true
  }
});

module.exports = mongoose.model('Usuario', usuarioSchema);