const mongoose = require('mongoose');

const clienteSchema = mongoose.Schema({
  run: {
    type: String,
    required: true,
    unique: true
  },
  nombreCompleto: String,
  direccion: String,
  comuna: String,
  provincia: String,
  region: String,
  fechaNacimiento: Date,
  sexo: String,
  email: {
    type: String,
    required: true,
    unique: true
  },
  telefono: String
});

module.exports = mongoose.model('Cliente', clienteSchema);