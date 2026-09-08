const express = require('express');
const { ApolloServer, gql } = require('apollo-server-express');
const mongoose = require('mongoose');
const cors = require('cors');

// Importar el modelo que creamos en models/Producto.js
const Producto = require('./models/Producto');

// 1. Esquema GraphQL (TypeDefs: tipos, queries y mutations)
const typeDefs = gql`
  type Producto {
    id: ID!
    nombre: String!
    categoria: String!
    precio: Float!
    disponible: Boolean
  }

  type Query {
    obtenerMenu: [Producto]
    obtenerProducto(id: ID!): Producto
  }

  type Mutation {
    crearProducto(
      nombre: String!
      categoria: String!
      precio: Float!
      disponible: Boolean
    ): Producto
  }
`;

// 2. Resolvers (Lógica que consulta o guarda en MongoDB)
const resolvers = {
  Query: {
    obtenerMenu: async () => {
      return await Producto.find();
    },
    obtenerProducto: async (_, { id }) => {
      return await Producto.findById(id);
    }
  },
  Mutation: {
    crearProducto: async (_, { nombre, categoria, precio, disponible }) => {
      const nuevoProducto = new Producto({
        nombre,
        categoria,
        precio,
        disponible: disponible !== undefined ? disponible : true
      });
      return await nuevoProducto.save();
    }
  }
};

// 3. Función principal de arranque del servidor
async function startServer() {
  const app = express();
  app.use(cors());

  // Crear instancia de Apollo Server con el esquema y los resolvers
  const apolloServer = new ApolloServer({
    typeDefs,
    resolvers
  });

  await apolloServer.start();
  apolloServer.applyMiddleware({ app });

  // Conectar con MongoDB local (usará la base de datos fukusuke_delivery)
  await mongoose.connect('mongodb://127.0.0.1:27017/fukusuke_delivery');
  console.log('Base de datos conectada exitosamente a MongoDB');

  // Levantar el servidor Express
  const PORT = 4000;
  app.listen(PORT, () => {
    console.log(`Servidor corriendo en: http://localhost:${PORT}${apolloServer.graphqlPath}`);
  });
}

startServer();