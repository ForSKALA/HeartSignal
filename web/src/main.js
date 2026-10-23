import { createApp } from "vue";
import { createRouter, createWebHashHistory } from "vue-router";
import App from "./App.vue";
import AuthView from "./views/AuthView.vue";
import HomeView from "./views/HomeView.vue";
import ChatbotView from "./views/ChatbotView.vue";
import "./style.css";

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/login" },
    { path: "/login", component: AuthView, props: { mode: "login" } },
    { path: "/signup", component: AuthView, props: { mode: "signup" } },
    { path: "/home", component: HomeView },
    { path: "/chatbot", component: ChatbotView },
    { path: "/:pathMatch(.*)*", redirect: "/login" },
  ],
  scrollBehavior() {
    return { top: 0 };
  },
});

createApp(App).use(router).mount("#app");
